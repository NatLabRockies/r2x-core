"""Tests for :class:`r2x_core.plugin_base.Plugin` base class."""

from tempfile import TemporaryDirectory

import pytest
from rust_ok import Err, Ok

from r2x_core import Plugin, PluginConfig, PluginContext, System
from r2x_core.exceptions import PluginError
from r2x_core.store import DataStore


class SimpleConfig(PluginConfig):
    """Minimal config for testing."""

    name: str = "test"


class BuildPlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_build."""

    def on_build(self):
        """Build a system."""
        system = System(name=self.config.name)
        return Ok(system)


class TransformPlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_transform."""

    def on_transform(self):
        """Transform system."""
        self.system.name = f"{self.system.name}_transformed"
        return Ok(self.system)


class ExportPlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_export."""

    def on_export(self):
        """Export system."""
        return Ok(None)


class ValidatePlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_validate."""

    def on_validate(self):
        """Validate config."""
        return Ok(None)


class PreparePlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_prepare."""

    def on_prepare(self):
        """Prepare for build."""
        return Ok(None)


class UpgradePlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_upgrade."""

    def on_upgrade(self):
        """Upgrade system."""
        self.ctx.system = System(name=f"{self.ctx.system.name}_upgraded")  # type: ignore
        return Ok(self.ctx.system)


class TranslatePlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_translate."""

    def on_translate(self):
        """Translate source to target."""
        target = System(name=f"{self.source_system.name}_translated")
        return Ok(target)


class CleanupPlugin(Plugin[SimpleConfig]):
    """Plugin that implements on_cleanup."""

    def on_cleanup(self):
        """Cleanup resources."""
        return Ok(None)


class FailValidatePlugin(Plugin[SimpleConfig]):
    """Plugin that fails validation."""

    def on_validate(self):
        """Fail validation."""
        return Err("Validation failed")


class FailPreparePlugin(Plugin[SimpleConfig]):
    """Plugin that fails prepare."""

    def on_prepare(self):
        """Fail prepare."""
        return Err("Prepare failed")


class FailUpgradePlugin(Plugin[SimpleConfig]):
    """Plugin that fails upgrade."""

    def on_upgrade(self):
        """Fail upgrade."""
        return Err("Upgrade failed")


class FailBuildPlugin(Plugin[SimpleConfig]):
    """Plugin that fails build."""

    def on_build(self):
        """Fail build."""
        return Err("Build failed")


class FailTransformPlugin(Plugin[SimpleConfig]):
    """Plugin that fails transform."""

    def on_transform(self):
        """Fail transform."""
        return Err("Transform failed")


class FailTranslatePlugin(Plugin[SimpleConfig]):
    """Plugin that fails translate."""

    def on_translate(self):
        """Fail translate."""
        return Err("Translate failed")


class FailExportPlugin(Plugin[SimpleConfig]):
    """Plugin that fails export."""

    def on_export(self):
        """Fail export."""
        return Err("Export failed")


class MultiHookPlugin(Plugin[SimpleConfig]):
    """Plugin with multiple hooks."""

    def on_validate(self):
        """Validate."""
        return Ok(None)

    def on_prepare(self):
        """Prepare."""
        return Ok(None)

    def on_build(self):
        """Build."""
        system = System(name=self.config.name)
        return Ok(system)

    def on_transform(self):
        """Transform."""
        self.system.name = f"{self.system.name}_transformed"
        return Ok(self.system)

    def on_export(self):
        """Export."""
        return Ok(None)

    def on_cleanup(self):
        """Cleanup."""
        return Ok(None)


# Tests for __init__ and from_context


pytestmark = pytest.mark.plugin


def test_plugin_init():
    """Test plugin initialization."""
    plugin = BuildPlugin()
    assert plugin is not None


def test_plugin_from_context():
    """Test creating plugin from context."""
    ctx = PluginContext(config=SimpleConfig(name="test"))
    plugin = BuildPlugin.from_context(ctx)
    assert plugin.ctx is ctx
    assert plugin.config.name == "test"


# Tests for properties


def test_config_property():
    """Test config property access."""
    ctx = PluginContext(config=SimpleConfig(name="my_config"))
    plugin = BuildPlugin.from_context(ctx)
    assert plugin.config.name == "my_config"


def test_ctx_property():
    """Test ctx property access."""
    ctx = PluginContext(config=SimpleConfig(name="test"))
    plugin = BuildPlugin.from_context(ctx)
    assert plugin.ctx is ctx


def test_metadata_property():
    """Test metadata property access."""
    ctx = PluginContext(config=SimpleConfig(name="test"))
    ctx.metadata["key"] = "value"
    plugin = BuildPlugin.from_context(ctx)
    assert plugin.metadata["key"] == "value"


def test_store_property_success():
    """Test store property when store is provided."""
    with TemporaryDirectory() as tmpdir:
        store = DataStore(tmpdir)
        ctx = PluginContext(config=SimpleConfig(name="test"), store=store)
        plugin = BuildPlugin.from_context(ctx)
        assert plugin.store is store


def test_store_property_missing_raises():
    """Test store property raises when store is None."""
    ctx = PluginContext(config=SimpleConfig(name="test"), store=None)
    plugin = BuildPlugin.from_context(ctx)
    with pytest.raises(PluginError, match="DataStore not provided"):
        _ = plugin.store


def test_system_property_success():
    """Test system property when system is provided."""
    system = System(name="test_system")
    ctx = PluginContext(config=SimpleConfig(name="test"), system=system)
    plugin = TransformPlugin.from_context(ctx)
    assert plugin.system is system


def test_system_property_missing_raises():
    """Test system property raises when system is None."""
    ctx = PluginContext(config=SimpleConfig(name="test"), system=None)
    plugin = TransformPlugin.from_context(ctx)
    with pytest.raises(PluginError, match="System not provided"):
        _ = plugin.system


def test_source_system_property_success():
    """Test source_system property when provided."""
    source = System(name="source")
    ctx = PluginContext(
        config=SimpleConfig(name="test"),
        source_system=source,
    )
    plugin = TranslatePlugin.from_context(ctx)
    assert plugin.source_system is source


def test_source_system_property_missing_raises():
    """Test source_system property raises when missing."""
    ctx = PluginContext(config=SimpleConfig(name="test"), source_system=None)
    plugin = TranslatePlugin.from_context(ctx)
    with pytest.raises(PluginError, match="Source system not provided"):
        _ = plugin.source_system


def test_target_system_property_success():
    """Test target_system property when provided."""
    target = System(name="target")
    ctx = PluginContext(
        config=SimpleConfig(name="test"),
        target_system=target,
    )
    plugin = ExportPlugin.from_context(ctx)
    assert plugin.target_system is target


def test_target_system_property_missing_raises():
    """Test target_system property raises when missing."""
    ctx = PluginContext(config=SimpleConfig(name="test"), target_system=None)
    plugin = ExportPlugin.from_context(ctx)
    with pytest.raises(PluginError, match="Target system not available"):
        _ = plugin.target_system


# Tests for get_config_type


def test_get_config_type():
    """Test extracting config type from plugin."""
    config_type = BuildPlugin.get_config_type()
    assert config_type is SimpleConfig


def test_get_config_type_with_inheritance():
    """Test config type extraction with plugin inheritance."""

    class DerivedConfig(SimpleConfig):
        extra: str = "default"

    class DerivedPlugin(Plugin[DerivedConfig]):
        def on_build(self):
            return Ok(System(name="test"))

    config_type = DerivedPlugin.get_config_type()
    assert config_type is DerivedConfig


def test_get_config_type_base_plugin():
    """Test config type extraction when called on base Plugin class."""
    # When called on Plugin (not a subclass), it falls back to ConfigT (which is unbound)
    config_type = Plugin.get_config_type()
    # ConfigT is a TypeVar, not a concrete class
    assert config_type is not None


# Tests for get_implemented_hooks


def test_get_implemented_hooks_single_hook():
    """Test detecting single implemented hook."""
    hooks = BuildPlugin.get_implemented_hooks()
    assert hooks == {"on_build"}


def test_get_implemented_hooks_multiple_hooks():
    """Test detecting multiple implemented hooks."""
    hooks = MultiHookPlugin.get_implemented_hooks()
    expected = {
        "on_validate",
        "on_prepare",
        "on_build",
        "on_transform",
        "on_export",
        "on_cleanup",
    }
    assert hooks == expected


def test_get_implemented_hooks_no_hooks():
    """Test plugin with no hooks."""
    hooks = Plugin.get_implemented_hooks()
    assert hooks == set()


def test_get_implemented_hooks_validate():
    """Test on_validate detection."""
    hooks = ValidatePlugin.get_implemented_hooks()
    assert "on_validate" in hooks


def test_get_implemented_hooks_prepare():
    """Test on_prepare detection."""
    hooks = PreparePlugin.get_implemented_hooks()
    assert "on_prepare" in hooks


def test_get_implemented_hooks_upgrade():
    """Test on_upgrade detection."""
    hooks = UpgradePlugin.get_implemented_hooks()
    assert "on_upgrade" in hooks


def test_get_implemented_hooks_transform():
    """Test on_transform detection."""
    hooks = TransformPlugin.get_implemented_hooks()
    assert "on_transform" in hooks


def test_get_implemented_hooks_translate():
    """Test on_translate detection."""
    hooks = TranslatePlugin.get_implemented_hooks()
    assert "on_translate" in hooks


def test_get_implemented_hooks_export():
    """Test on_export detection."""
    hooks = ExportPlugin.get_implemented_hooks()
    assert "on_export" in hooks


def test_get_implemented_hooks_cleanup():
    """Test on_cleanup detection."""
    hooks = CleanupPlugin.get_implemented_hooks()
    assert "on_cleanup" in hooks


def test_get_implemented_hooks_inherited():
    """Test hook detection with inheritance."""

    class BasePluginWithHook(Plugin[SimpleConfig]):
        """Base with a hook."""

        def on_validate(self):
            return Ok(None)

    class DerivedPluginNoNewHook(BasePluginWithHook):
        """Derived that inherits the hook."""

    hooks = DerivedPluginNoNewHook.get_implemented_hooks()
    assert "on_validate" in hooks


@pytest.mark.parametrize("disabled_hook", [None, False])
def test_non_callable_hooks_are_neither_discovered_nor_executed(disabled_hook: object) -> None:
    class DisabledBuild(BuildPlugin):
        on_build = disabled_hook

    context = PluginContext(config=SimpleConfig(name="disabled"))

    assert "on_build" not in DisabledBuild.get_implemented_hooks()
    assert DisabledBuild.from_context(context).run().system is None


# Tests for run() method


def test_run_with_build_hook():
    """Test run executes on_build."""
    ctx = PluginContext(config=SimpleConfig(name="test_system"))
    plugin = BuildPlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx.system is not None
    assert result_ctx.system.name == "test_system"


def test_run_with_context_override():
    """Test run with context override parameter."""
    ctx1 = PluginContext(config=SimpleConfig(name="system1"))
    ctx2 = PluginContext(config=SimpleConfig(name="system2"))

    plugin = BuildPlugin.from_context(ctx1)
    result_ctx = plugin.run(ctx=ctx2)

    assert result_ctx.system.name == "system2"  # type: ignore
    assert plugin.ctx is ctx2


def test_run_with_transform_hook():
    """Test run executes on_transform."""
    system = System(name="original")
    ctx = PluginContext(config=SimpleConfig(), system=system)
    plugin = TransformPlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx.system.name == "original_transformed"  # type: ignore


def test_run_with_upgrade_hook():
    """Test run executes on_upgrade."""
    system = System(name="v1")
    ctx = PluginContext(config=SimpleConfig(), system=system)
    plugin = UpgradePlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx.system.name == "v1_upgraded"  # type: ignore


def test_run_with_translate_hook():
    """Test run executes on_translate."""
    source = System(name="source")
    ctx = PluginContext(config=SimpleConfig(), source_system=source)
    plugin = TranslatePlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx.target_system is not None
    assert result_ctx.target_system.name == "source_translated"


def test_run_with_export_hook():
    """Test run executes on_export."""
    system = System(name="to_export")
    ctx = PluginContext(config=SimpleConfig(), system=system)
    plugin = ExportPlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx is ctx


def test_run_with_validate_hook():
    """Test run executes on_validate."""
    ctx = PluginContext(config=SimpleConfig())
    plugin = ValidatePlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx is ctx


def test_run_with_prepare_hook():
    """Test run executes on_prepare."""
    ctx = PluginContext(config=SimpleConfig())
    plugin = PreparePlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx is ctx


def test_run_with_cleanup_hook():
    """Test run executes on_cleanup."""
    ctx = PluginContext(config=SimpleConfig())
    plugin = CleanupPlugin.from_context(ctx)
    result_ctx = plugin.run()

    assert result_ctx is ctx


def test_run_with_multiple_hooks():
    """Test run executes all hooks in order."""
    ctx = PluginContext(config=SimpleConfig(name="multi"))
    plugin = MultiHookPlugin.from_context(ctx)
    result_ctx = plugin.run()

    # Build creates system, transform modifies it, export processes it
    assert result_ctx.system is not None
    assert result_ctx.system.name == "multi_transformed"


def test_run_validate_failure():
    """Test run raises on validation failure."""
    ctx = PluginContext(config=SimpleConfig())
    plugin = FailValidatePlugin.from_context(ctx)

    with pytest.raises(PluginError, match="validation failed"):
        plugin.run()


def test_run_prepare_failure():
    """Test run raises on prepare failure."""
    ctx = PluginContext(config=SimpleConfig())
    plugin = FailPreparePlugin.from_context(ctx)

    with pytest.raises(PluginError, match="prepare failed"):
        plugin.run()


def test_run_upgrade_failure():
    """Test run raises on upgrade failure."""
    ctx = PluginContext(config=SimpleConfig(), system=System(name="test"))
    plugin = FailUpgradePlugin.from_context(ctx)

    with pytest.raises(PluginError, match="upgrade failed"):
        plugin.run()


def test_run_build_failure():
    """Test run raises on build failure."""
    ctx = PluginContext(config=SimpleConfig())
    plugin = FailBuildPlugin.from_context(ctx)

    with pytest.raises(PluginError, match="build failed"):
        plugin.run()


def test_run_transform_failure():
    """Test run raises on transform failure."""
    ctx = PluginContext(config=SimpleConfig(), system=System(name="test"))
    plugin = FailTransformPlugin.from_context(ctx)

    with pytest.raises(PluginError, match="transform failed"):
        plugin.run()


def test_run_translate_failure():
    """Test run raises on translate failure."""
    ctx = PluginContext(config=SimpleConfig(), source_system=System(name="source"))
    plugin = FailTranslatePlugin.from_context(ctx)

    with pytest.raises(PluginError, match="translate failed"):
        plugin.run()


def test_run_export_failure():
    """Test run raises on export failure."""
    ctx = PluginContext(config=SimpleConfig(), system=System(name="test"))
    plugin = FailExportPlugin.from_context(ctx)

    with pytest.raises(PluginError, match="export failed"):
        plugin.run()


# Test lifecycle order


class LifecycleTracker(Plugin[SimpleConfig]):
    """Plugin that tracks hook execution order."""

    call_order: list[str] = []  # noqa: RUF012

    def on_validate(self):
        """Track validation."""
        self.call_order.append("validate")
        return Ok(None)

    def on_prepare(self):
        """Track prepare."""
        self.call_order.append("prepare")
        return Ok(None)

    def on_upgrade(self):
        """Track upgrade."""
        self.call_order.append("upgrade")
        system = System(name="upgraded")
        return Ok(system)

    def on_build(self):
        """Track build."""
        self.call_order.append("build")
        return Ok(System(name="built"))

    def on_transform(self):
        """Track transform."""
        self.call_order.append("transform")
        return Ok(self.system)

    def on_translate(self):
        """Track translate."""
        self.call_order.append("translate")
        return Ok(System(name="translated"))

    def on_export(self):
        """Track export."""
        self.call_order.append("export")
        return Ok(None)

    def on_cleanup(self):
        """Track cleanup."""
        self.call_order.append("cleanup")
        return Ok(None)


def test_lifecycle_order():
    """Test hooks are called in correct order."""
    LifecycleTracker.call_order = []
    ctx = PluginContext(config=SimpleConfig())
    plugin = LifecycleTracker.from_context(ctx)
    plugin.run()

    expected = ["validate", "prepare", "upgrade", "build", "transform", "translate", "export", "cleanup"]
    assert LifecycleTracker.call_order == expected


def test_run_rejects_plain_hook_result_before_export():
    calls: list[str] = []

    class InvalidBuildPlugin(Plugin[SimpleConfig]):
        def on_build(self):
            return None

        def on_export(self):
            calls.append("export")
            return Ok(None)

    plugin = InvalidBuildPlugin.from_context(PluginContext(config=SimpleConfig()))

    with pytest.raises(TypeError, match="InvalidBuildPlugin on_build must return Ok or Err"):
        plugin.run()

    assert calls == []


def test_run_preserves_exception_from_err_hook():
    failure = ValueError("invalid build")

    class ErrorBuildPlugin(Plugin[SimpleConfig]):
        def on_build(self):
            return Err(failure)

    plugin = ErrorBuildPlugin.from_context(PluginContext(config=SimpleConfig()))

    with pytest.raises(PluginError, match="build failed") as raised:
        plugin.run()

    assert raised.value.__cause__ is failure
