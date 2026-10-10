"""Typed errors exposed by CohortSeal."""


class CohortSealError(Exception):
    """Base class for expected CohortSeal failures."""


class ManifestError(CohortSealError):
    """A manifest is malformed or internally inconsistent."""


class ConfigurationError(CohortSealError):
    """Configuration values are missing or invalid."""


class SplitError(CohortSealError):
    """A requested split cannot satisfy its declared constraints."""


class StorageError(CohortSealError):
    """Persistent state could not be read or updated."""


class PluginError(CohortSealError):
    """A plugin failed validation or execution."""
