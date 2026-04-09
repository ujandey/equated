"""
Services — Kill-Storm Tracker

Provides distributed system protection against localized IP and Subnet sweeps
causing cascading failures. Actively balances security vs NAT collateral damage.
"""

import ipaddress
from dataclasses import dataclass

import structlog

from config.settings import settings
from cache.redis_cache import redis_client

logger = structlog.get_logger("equated.services.kill_storm_tracker")


@dataclass
class BlackholeDecision:
    block: bool
    reason: str | None = None


class KillStormTracker:
    """
    Multi-level kill tracking with NAT awareness.
    
    Priority order: user_id > IP > subnet
    
    Subnet blocking ONLY triggers if:
    - Kill count > KILL_STORM_THRESHOLD_PER_SUBNET
    - AND unique user_ids on that subnet < KILL_STORM_SUBNET_MIN_USERS
      (if many different users => probably shared NAT, don't block entire subnet)
    """

    def _extract_subnet(self, ip: str, prefix: int = 24) -> str:
        """Extracts the subnet from an IP address. Default to /24 for IPv4."""
        try:
            network = ipaddress.ip_network(f"{ip}/{prefix}", strict=False)
            return str(network.network_address)
        except ValueError:
            return ip  # Fallback to direct IP mapping if malformed

    async def record_kill(self, ip: str, user_id: str | None, tier: str = "free"):
        """
        Record a kill event structurally.
        """
        subnet = self._extract_subnet(ip)
        window = settings.KILL_STORM_WINDOW_SECONDS
        long_window = settings.KILL_STORM_LONG_WINDOW_SECONDS
        
        pipe = redis_client.client.pipeline()

        # 0. Global Anomaly Tracking (Fix 1: Track distinct subnets under squeeze)
        global_key = "rate:kill:global:60s"
        global_subnets_key = "rate:kill:global_subnets:60s"
        pipe.incr(global_key)
        pipe.expire(global_key, window)
        pipe.sadd(global_subnets_key, subnet)
        pipe.expire(global_subnets_key, window)

        # 1. IP Tracking (Short & Long Windows)
        pipe.incr(f"rate:kill:ip:{ip}:short")
        pipe.expire(f"rate:kill:ip:{ip}:short", window)
        pipe.incr(f"rate:kill:ip:{ip}:long")
        pipe.expire(f"rate:kill:ip:{ip}:long", long_window)

        # 2. Subnet Tracking (Short)
        subnet_key = f"rate:kill:subnet:{subnet}"
        pipe.incr(subnet_key)
        pipe.expire(subnet_key, window)
        
        # 3. Track unique users AND auth ratio on this subnet
        subnet_users_key = f"rate:kill:subnet_users:{subnet}"
        subnet_auth_count_key = f"rate:kill:subnet_auth_count:{subnet}"
        subnet_total_count_key = f"rate:kill:subnet_total_count:{subnet}"
        
        pipe.incr(subnet_total_count_key)
        pipe.expire(subnet_total_count_key, window)
        if user_id:
             pipe.incr(subnet_auth_count_key)
             pipe.expire(subnet_auth_count_key, window)
             pipe.sadd(subnet_users_key, user_id)
        else:
             pipe.sadd(subnet_users_key, f"anon_{ip}") # Anon connections from same IP count as 1
        pipe.expire(subnet_users_key, window)

        # 4. User Tracking (Precision Sniper) 
        if user_id:
             pipe.incr(f"rate:kill:user:{user_id}:short")
             pipe.expire(f"rate:kill:user:{user_id}:short", window)
             pipe.incr(f"rate:kill:user:{user_id}:long")
             pipe.expire(f"rate:kill:user:{user_id}:long", long_window)
             
        await pipe.execute()
        logger.debug("kill_recorded", ip=ip, subnet=subnet, user_id=user_id)

    async def check_blackhole(self, ip: str, user_id: str | None) -> BlackholeDecision:
        """
        Check whether this request source is blackholed due to generating
        too many system kills/crashes.
        """
        subnet = self._extract_subnet(ip)
        pipe = redis_client.client.pipeline()
        
        # Pull all keys simultaneously
        pipe.get(f"rate:kill:ip:{ip}:short")
        pipe.get(f"rate:kill:ip:{ip}:long")
        pipe.get(f"rate:kill:subnet:{subnet}")
        pipe.get(f"rate:kill:subnet_trust_weight:{subnet}")
        pipe.get("rate:kill:global:60s")
        pipe.scard("rate:kill:global_subnets:60s")
        pipe.exists("rate:kill:global_hysteresis")
        if user_id:
            pipe.get(f"rate:kill:user:{user_id}:short")
            pipe.get(f"rate:kill:user:{user_id}:long")
            
        results = await pipe.execute()
        
        ip_short = int(results[0] or 0)
        ip_long = int(results[1] or 0)
        subnet_kills = int(results[2] or 0)
        subnet_trust_raw = results[3]
        subnet_trust = float(subnet_trust_raw) if subnet_trust_raw else 0.0
        global_kills = int(results[4] or 0)
        global_subnets = int(results[5] or 0)
        in_hysteresis = bool(results[6])
        
        user_short = int(results[7] or 0) if user_id else 0
        user_long = int(results[8] or 0) if user_id else 0

        # Note: Long Window thresholds are implicitly 3x short window (e.g. 15 kills in 5 mins instead of 5 in 1 min)
        # 1. User precision block (Lowest collateral)
        if user_short > settings.KILL_STORM_THRESHOLD_PER_IP or user_long > (settings.KILL_STORM_THRESHOLD_PER_IP * 3):
            logger.warning("blackhole_triggered_user", user_id=user_id, short=user_short, long=user_long)
            return BlackholeDecision(block=True, reason="User kill-storm threshold exceeded.")

        # 2. IP level block
        if ip_short > settings.KILL_STORM_THRESHOLD_PER_IP or ip_long > (settings.KILL_STORM_THRESHOLD_PER_IP * 3):
            logger.warning("blackhole_triggered_ip", ip=ip, short=ip_short, long=ip_long)
            return BlackholeDecision(block=True, reason="IP kill-storm threshold exceeded.")

        # 3. Subnet block (NAT Aware using Explicit Trust Weights Fix 4)
        if subnet_kills > settings.KILL_STORM_THRESHOLD_PER_SUBNET:
             if subnet_trust < settings.KILL_STORM_SUBNET_MIN_USERS:
                 logger.warning("blackhole_triggered_subnet", subnet=subnet, count=subnet_kills, trust=subnet_trust)
                 return BlackholeDecision(block=True, reason="Subnet kill-storm threshold exceeded (Low Trust Entropy).")
        
        # 4. Global Anomaly Signal (Fix 1 & Fix 2: Oscillation Hysteresis)
        is_global_breach = global_kills > settings.KILL_STORM_GLOBAL_THRESHOLD and global_subnets > 2
        if is_global_breach or in_hysteresis:
            if is_global_breach:
                # Refresh hysteresis cooldown (enter fast, exit slow)
                await redis_client.client.set("rate:kill:global_hysteresis", "1", ex=15)
            # We don't drop here - this signal passes through to tighten AST limits
            return BlackholeDecision(block=False, reason="global_anomaly_active")
            
        return BlackholeDecision(block=False)

kill_storm_tracker = KillStormTracker()
