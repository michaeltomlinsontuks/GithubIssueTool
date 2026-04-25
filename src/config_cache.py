"""In-memory config cache for MCP server."""

from __future__ import annotations

from pathlib import Path
from threading import Lock

from src.config_loader import load_project_config
from src.models import ProjectConfig


class ConfigCache:
    """Singleton cache for ProjectConfig objects.
    
    Loads config from disk on demand, caches in memory.
    Thread-safe for concurrent tool calls.
    """

    _instance: ConfigCache | None = None
    _lock = Lock()
    _cache: dict[str, ProjectConfig] = {}
    _cache_lock = Lock()

    def __new__(cls) -> ConfigCache:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def get(self, config_dir: str | Path) -> ProjectConfig:
        """Get config, loading from disk if not cached.
        
        Args:
            config_dir: Path to config directory
            
        Returns:
            ProjectConfig object
            
        Raises:
            ValueError: If config is invalid
            FileNotFoundError: If config files not found
        """
        config_dir = Path(config_dir).resolve()
        key = str(config_dir)

        with self._cache_lock:
            if key in self._cache:
                return self._cache[key]

            config = load_project_config(config_dir)
            self._cache[key] = config
            return config

    def refresh(self, config_dir: str | Path) -> ProjectConfig:
        """Force reload config from disk.
        
        Called after gather-config to pick up new changes.
        
        Args:
            config_dir: Path to config directory
            
        Returns:
            Freshly-loaded ProjectConfig object
            
        Raises:
            ValueError: If config is invalid
            FileNotFoundError: If config files not found
        """
        config_dir = Path(config_dir).resolve()
        key = str(config_dir)

        with self._cache_lock:
            config = load_project_config(config_dir)
            self._cache[key] = config
            return config

    def clear(self, config_dir: str | Path | None = None) -> None:
        """Clear cache entry or entire cache.
        
        Args:
            config_dir: Specific config dir to clear, or None to clear all
        """
        with self._cache_lock:
            if config_dir is None:
                self._cache.clear()
            else:
                key = str(Path(config_dir).resolve())
                self._cache.pop(key, None)
