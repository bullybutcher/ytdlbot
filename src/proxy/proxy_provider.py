"""Base class for proxy providers."""


class ProxyProvider:
    """Base class for proxy providers."""

    def fetch_proxies(self):
        """Fetch proxies from the provider.
        
        Returns:
            List of proxy dictionaries with keys: host, port, username (optional), password (optional), city (optional), country
        """
        raise NotImplementedError

