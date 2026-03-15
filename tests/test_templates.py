"""Tests for the argus_mcp.bridge.container.templates package.

Covers:
- RuntimeConfig defaults and override logic (models.py)
- TemplateData auto-detection and field defaults (models.py)
- Input validation: package names, system deps, build env (validation.py)
- Jinja2 template rendering engine (engine.py)
- Dockerfile generators with RuntimeConfig + validation (_generators.py)
- Backwards-compatible public API re-exports (__init__.py)
"""

from __future__ import annotations

import pytest

# models.py ───────────────────────────────────────────────────────────
from argus_mcp.bridge.container.templates.models import (
    RUNTIME_DEFAULTS,
    RuntimeConfig,
    TemplateData,
)


class TestRuntimeDefaults:
    """RUNTIME_DEFAULTS dict structure."""

    def test_uvx_defaults_present(self):
        assert "uvx" in RUNTIME_DEFAULTS
        assert "builder_image" in RUNTIME_DEFAULTS["uvx"]

    def test_npx_defaults_present(self):
        assert "npx" in RUNTIME_DEFAULTS
        assert "builder_image" in RUNTIME_DEFAULTS["npx"]

    def test_uvx_default_image(self):
        assert RUNTIME_DEFAULTS["uvx"]["builder_image"] == "python:3.13-slim"

    def test_npx_default_image(self):
        assert RUNTIME_DEFAULTS["npx"]["builder_image"] == "node:22-alpine"


class TestRuntimeConfig:
    """RuntimeConfig dataclass and factory method."""

    def test_for_uvx_defaults(self):
        rc = RuntimeConfig.for_transport("uvx")
        assert rc.builder_image == "python:3.13-slim"
        assert rc.additional_packages == ["ca-certificates", "git"]

    def test_for_npx_defaults(self):
        rc = RuntimeConfig.for_transport("npx")
        assert rc.builder_image == "node:22-alpine"
        assert rc.additional_packages == ["ca-certificates", "git"]

    def test_unknown_transport(self):
        rc = RuntimeConfig.for_transport("unknown")
        assert rc.builder_image == ""
        assert rc.additional_packages == []

    def test_override_builder_image(self):
        rc = RuntimeConfig.for_transport(
            "uvx",
            overrides={"builder_image": "python:3.12-slim"},
        )
        assert rc.builder_image == "python:3.12-slim"

    def test_override_additional_packages(self):
        rc = RuntimeConfig.for_transport(
            "npx",
            overrides={"additional_packages": ["curl", "wget"]},
        )
        assert rc.additional_packages == ["curl", "wget"]

    def test_override_both(self):
        rc = RuntimeConfig.for_transport(
            "uvx",
            overrides={
                "builder_image": "python:3.11-bookworm",
                "additional_packages": ["git"],
            },
        )
        assert rc.builder_image == "python:3.11-bookworm"
        assert rc.additional_packages == ["git"]

    def test_none_overrides(self):
        rc = RuntimeConfig.for_transport("uvx", overrides=None)
        assert rc.builder_image == "python:3.13-slim"

    def test_empty_overrides(self):
        rc = RuntimeConfig.for_transport("uvx", overrides={})
        assert rc.builder_image == "python:3.13-slim"


class TestTemplateData:
    """TemplateData auto-detection and fields."""

    def test_alpine_detection_positive(self):
        td = TemplateData(
            package="test",
            package_clean="test",
            binary="test",
            builder_image="node:22-alpine",
        )
        assert td.is_alpine is True

    def test_alpine_detection_negative(self):
        td = TemplateData(
            package="test",
            package_clean="test",
            binary="test",
            builder_image="python:3.13-slim",
        )
        assert td.is_alpine is False

    def test_alpine_detection_case_insensitive(self):
        td = TemplateData(
            package="test",
            package_clean="test",
            binary="test",
            builder_image="node:22-ALPINE",
        )
        assert td.is_alpine is True

    def test_defaults(self):
        td = TemplateData(
            package="pkg",
            package_clean="pkg",
            binary="bin",
            builder_image="python:3.13-slim",
        )
        assert td.system_deps == []
        assert td.build_env == {}
        assert td.additional_packages == []
        assert td.is_alpine is False


# validation.py ───────────────────────────────────────────────────────

from argus_mcp.bridge.container.templates.validation import (
    ValidationError,
    validate_build_env_key,
    validate_build_env_value,
    validate_package_name,
    validate_system_deps,
)


class TestValidatePackageName:
    """Package name validation."""

    def test_valid_simple(self):
        assert validate_package_name("mcp-server-analyzer") == "mcp-server-analyzer"

    def test_valid_scoped(self):
        assert validate_package_name("@scope/pkg") == "@scope/pkg"

    def test_valid_with_version(self):
        assert validate_package_name("pkg@1.2.3") == "pkg@1.2.3"

    def test_strips_whitespace(self):
        assert validate_package_name("  pkg  ") == "pkg"

    def test_rejects_empty(self):
        with pytest.raises(ValidationError, match="empty"):
            validate_package_name("")

    def test_rejects_whitespace_only(self):
        with pytest.raises(ValidationError, match="empty"):
            validate_package_name("   ")

    def test_rejects_semicolon(self):
        with pytest.raises(ValidationError, match="unsafe"):
            validate_package_name("pkg; rm -rf /")

    def test_rejects_backtick(self):
        with pytest.raises(ValidationError, match="unsafe"):
            validate_package_name("pkg`whoami`")

    def test_rejects_dollar(self):
        with pytest.raises(ValidationError, match="unsafe"):
            validate_package_name("pkg$(echo bad)")

    def test_rejects_pipe(self):
        with pytest.raises(ValidationError, match="unsafe"):
            validate_package_name("pkg|cat /etc/passwd")

    def test_rejects_too_long(self):
        with pytest.raises(ValidationError, match="too long"):
            validate_package_name("a" * 257)

    def test_max_length_ok(self):
        result = validate_package_name("a" * 256)
        assert len(result) == 256


class TestValidateSystemDeps:
    """System dependency name validation."""

    def test_valid_list(self):
        assert validate_system_deps(["ripgrep", "git"]) == ["ripgrep", "git"]

    def test_strips_whitespace(self):
        assert validate_system_deps(["  ripgrep  "]) == ["ripgrep"]

    def test_skips_empty(self):
        assert validate_system_deps(["ripgrep", "", "  "]) == ["ripgrep"]

    def test_valid_with_dots_dashes(self):
        # Library names like libssl1.1, lib32-glibc
        assert validate_system_deps(["libssl1.1"]) == ["libssl1.1"]
        assert validate_system_deps(["lib-dev"]) == ["lib-dev"]

    def test_valid_with_plus(self):
        # Packages like g++, libc++
        assert validate_system_deps(["g++"]) == ["g++"]

    def test_rejects_semicolon(self):
        with pytest.raises(ValidationError, match="unsafe"):
            validate_system_deps(["git; echo pwned"])

    def test_rejects_backtick(self):
        with pytest.raises(ValidationError, match="unsafe"):
            validate_system_deps(["`whoami`"])

    def test_rejects_space_in_name(self):
        with pytest.raises(ValidationError, match="not a valid"):
            validate_system_deps(["two words"])

    def test_rejects_leading_dash(self):
        with pytest.raises(ValidationError, match="not a valid"):
            validate_system_deps(["-badpkg"])

    def test_empty_list(self):
        assert validate_system_deps([]) == []


class TestValidateBuildEnvKey:
    """Build environment variable key validation."""

    def test_valid_key(self):
        assert validate_build_env_key("MY_TOKEN") == "MY_TOKEN"

    def test_valid_with_digits(self):
        assert validate_build_env_key("VAR123") == "VAR123"

    def test_rejects_lowercase(self):
        with pytest.raises(ValidationError, match="uppercase"):
            validate_build_env_key("my_var")

    def test_rejects_leading_digit(self):
        with pytest.raises(ValidationError, match="uppercase"):
            validate_build_env_key("1VAR")

    def test_rejects_reserved_path(self):
        with pytest.raises(ValidationError, match="reserved"):
            validate_build_env_key("PATH")

    def test_rejects_reserved_home(self):
        with pytest.raises(ValidationError, match="reserved"):
            validate_build_env_key("HOME")

    def test_rejects_reserved_uv_tool_dir(self):
        with pytest.raises(ValidationError, match="reserved"):
            validate_build_env_key("UV_TOOL_DIR")


class TestValidateBuildEnvValue:
    """Build environment variable value validation."""

    def test_valid_simple(self):
        assert validate_build_env_value("hello123") == "hello123"

    def test_valid_with_special_chars(self):
        assert validate_build_env_value("a=b,c:d/e") == "a=b,c:d/e"

    def test_rejects_semicolon(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_build_env_value("a;b")

    def test_rejects_backtick(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_build_env_value("`cmd`")

    def test_rejects_dollar(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_build_env_value("$VAR")

    def test_rejects_pipe(self):
        with pytest.raises(ValidationError, match="dangerous"):
            validate_build_env_value("a|b")


# engine.py ───────────────────────────────────────────────────────────

from argus_mcp.bridge.container.templates.engine import render_template


class TestRenderTemplate:
    """Jinja2 template rendering engine."""

    def test_uvx_template_renders(self):
        result = render_template(
            "uvx.dockerfile.j2",
            {
                "builder_image": "python:3.13-slim",
                "is_alpine": False,
                "install_cmd": "uv tool install test-pkg",
                "build_env": {},
                "system_deps": [],
                "additional_packages": [],
                "binary": "test-pkg",
            },
        )
        assert "FROM python:3.13-slim" in result
        assert "uv tool install test-pkg" in result
        assert 'ENTRYPOINT ["test-pkg"]' in result

    def test_npx_template_renders(self):
        result = render_template(
            "npx.dockerfile.j2",
            {
                "builder_image": "node:22-alpine",
                "is_alpine": True,
                "package": "@scope/my-server@1.0",
                "package_clean": "@scope/my-server",
                "bin_name": "my-server",
                "build_env": {},
                "system_deps": [],
                "additional_packages": [],
            },
        )
        assert "FROM node:22-alpine" in result
        assert "npm install" in result
        assert "@scope/my-server@1.0" in result
        assert "__argus_entry" in result

    def test_uvx_with_system_deps(self):
        result = render_template(
            "uvx.dockerfile.j2",
            {
                "builder_image": "python:3.13-slim",
                "is_alpine": False,
                "install_cmd": "uv tool install pkg",
                "build_env": {},
                "system_deps": ["ripgrep", "git"],
                "additional_packages": [],
                "binary": "pkg",
            },
        )
        assert "apt-get install -y --no-install-recommends ripgrep git" in result

    def test_npx_with_system_deps_alpine(self):
        result = render_template(
            "npx.dockerfile.j2",
            {
                "builder_image": "node:22-alpine",
                "is_alpine": True,
                "package": "pkg",
                "package_clean": "pkg",
                "bin_name": "pkg",
                "build_env": {},
                "system_deps": ["ripgrep"],
                "additional_packages": [],
            },
        )
        assert "apk add --no-cache ripgrep" in result

    def test_uvx_alpine_system_deps(self):
        result = render_template(
            "uvx.dockerfile.j2",
            {
                "builder_image": "python:3.13-alpine",
                "is_alpine": True,
                "install_cmd": "uv tool install pkg",
                "build_env": {},
                "system_deps": ["curl"],
                "additional_packages": [],
                "binary": "pkg",
            },
        )
        assert "apk add --no-cache curl" in result

    def test_build_env_injection(self):
        result = render_template(
            "uvx.dockerfile.j2",
            {
                "builder_image": "python:3.13-slim",
                "is_alpine": False,
                "install_cmd": "uv tool install pkg",
                "build_env": {"MY_TOKEN": "abc123"},
                "system_deps": [],
                "additional_packages": [],
                "binary": "pkg",
            },
        )
        assert 'ARG MY_TOKEN="abc123"' in result
        assert 'ENV MY_TOKEN="${MY_TOKEN}"' in result

    def test_additional_packages(self):
        result = render_template(
            "uvx.dockerfile.j2",
            {
                "builder_image": "python:3.13-slim",
                "is_alpine": False,
                "install_cmd": "uv tool install pkg",
                "build_env": {},
                "system_deps": [],
                "additional_packages": ["wget", "jq"],
                "binary": "pkg",
            },
        )
        assert "apt-get install -y --no-install-recommends wget jq" in result


# _generators.py — public API ─────────────────────────────────────────

from argus_mcp.bridge.container.templates import (
    IMAGE_PREFIX,
    compute_image_tag,
    generate_npx_dockerfile,
    generate_uvx_dockerfile,
    parse_npx_args,
    parse_uvx_args,
)
from argus_mcp.bridge.container.templates._generators import (
    _compute_uvx_install_cmd,
    _npm_bin_name,
    _sanitize_image_name,
    _strip_version,
)


class TestStripVersion:
    """Version suffix removal for package names."""

    def test_simple(self):
        assert _strip_version("pkg@1.2.3") == "pkg"

    def test_scoped(self):
        assert _strip_version("@scope/pkg@1.2.3") == "@scope/pkg"

    def test_no_version(self):
        assert _strip_version("pkg") == "pkg"

    def test_scoped_no_version(self):
        assert _strip_version("@scope/pkg") == "@scope/pkg"


class TestSanitizeImageName:
    """Image name sanitisation for Docker tag safety."""

    def test_scoped_package(self):
        result = _sanitize_image_name("@scope/pkg")
        assert "@" not in result
        assert "/" not in result

    def test_simple_package(self):
        result = _sanitize_image_name("my-pkg")
        assert result == "my-pkg"


class TestNpmBinName:
    """NPM binary name heuristic."""

    def test_simple(self):
        assert _npm_bin_name("my-server") == "my-server"

    def test_scoped(self):
        assert _npm_bin_name("@scope/my-server") == "my-server"

    def test_with_version(self):
        assert _npm_bin_name("my-server@1.0.0") == "my-server@1.0.0"

    def test_scoped_with_version(self):
        assert _npm_bin_name("@scope/my-server@1.0.0") == "my-server@1.0.0"


class TestComputeUvxInstallCmd:
    """UVX install command generation."""

    def test_simple(self):
        cmd = _compute_uvx_install_cmd("my-pkg")
        assert cmd == "uv tool install my-pkg"

    def test_with_version(self):
        cmd = _compute_uvx_install_cmd("my-pkg@1.2.3")
        assert cmd == "uv tool install 'my-pkg==1.2.3'"

    def test_scoped_with_version(self):
        cmd = _compute_uvx_install_cmd("@scope/pkg@2.0")
        assert cmd == "uv tool install @scope/pkg@2.0"


class TestParseUvxArgs:
    """UVX argument parsing."""

    def test_basic(self):
        pkg, binary, extra = parse_uvx_args(["my-pkg"])
        assert pkg == "my-pkg"
        assert binary == "my-pkg"
        assert extra == []

    def test_with_extra_args(self):
        pkg, binary, extra = parse_uvx_args(["my-pkg", "--host", "0.0.0.0"])
        assert pkg == "my-pkg"
        assert extra == ["--host", "0.0.0.0"]

    def test_with_from_flag(self):
        pkg, binary, extra = parse_uvx_args(["--from", "my-pkg", "my-bin"])
        assert pkg == "my-pkg"
        assert binary == "my-bin"

    def test_with_version(self):
        pkg, binary, extra = parse_uvx_args(["my-pkg@1.0.0"])
        assert pkg == "my-pkg@1.0.0"
        assert binary == "my-pkg"


class TestParseNpxArgs:
    """NPX argument parsing."""

    def test_basic(self):
        pkg, extra = parse_npx_args(["@scope/my-server"])
        assert pkg == "@scope/my-server"
        assert extra == []

    def test_with_yes_flag(self):
        pkg, extra = parse_npx_args(["-y", "@scope/my-server", "--verbose"])
        assert pkg == "@scope/my-server"
        assert extra == ["--verbose"]


class TestGenerateUvxDockerfileWithRuntimeConfig:
    """UVX Dockerfile generation with RuntimeConfig."""

    def test_default_runtime(self):
        df = generate_uvx_dockerfile("my-pkg", "my-pkg")
        assert "FROM python:3.13-slim" in df
        assert "uv tool install my-pkg" in df
        assert 'ENTRYPOINT ["my-pkg"]' in df
        assert "nonroot" in df

    def test_custom_builder_image(self):
        rc = RuntimeConfig(builder_image="python:3.12-slim")
        df = generate_uvx_dockerfile("my-pkg", "my-pkg", runtime_config=rc)
        assert "FROM python:3.12-slim" in df

    def test_alpine_builder_image(self):
        rc = RuntimeConfig(builder_image="python:3.13-alpine")
        df = generate_uvx_dockerfile("my-pkg", "my-pkg", runtime_config=rc)
        assert "FROM python:3.13-alpine" in df
        # For alpine, system deps use apk
        df_with_deps = generate_uvx_dockerfile(
            "my-pkg",
            "my-pkg",
            system_deps=["curl"],
            runtime_config=rc,
        )
        assert "apk add --no-cache curl" in df_with_deps

    def test_system_deps_debian(self):
        df = generate_uvx_dockerfile("my-pkg", "my-pkg", system_deps=["ripgrep", "git"])
        assert "apt-get install -y --no-install-recommends ripgrep git" in df

    def test_additional_packages(self):
        rc = RuntimeConfig(
            builder_image="python:3.13-slim",
            additional_packages=["wget"],
        )
        df = generate_uvx_dockerfile("my-pkg", "my-pkg", runtime_config=rc)
        assert "apt-get install -y --no-install-recommends wget" in df

    def test_build_env(self):
        df = generate_uvx_dockerfile(
            "my-pkg",
            "my-pkg",
            build_env={"MY_VAR": "hello"},
        )
        assert 'ARG MY_VAR="hello"' in df
        assert 'ENV MY_VAR="${MY_VAR}"' in df

    def test_dependency_symlink_step(self):
        """Multi-stage build exposes dependency binaries."""
        df = generate_uvx_dockerfile("my-pkg", "my-pkg")
        assert "ln -s" in df
        assert "/opt/uv-tools/bin" in df

    def test_non_root_user(self):
        df = generate_uvx_dockerfile("my-pkg", "my-pkg")
        assert "USER nonroot" in df

    def test_validation_rejects_bad_package(self):
        with pytest.raises(ValidationError, match="unsafe"):
            generate_uvx_dockerfile("bad;pkg", "bad;pkg")

    def test_validation_rejects_bad_deps(self):
        with pytest.raises(ValidationError, match="unsafe"):
            generate_uvx_dockerfile("pkg", "pkg", system_deps=["evil;cmd"])

    def test_validation_rejects_bad_env_key(self):
        with pytest.raises(ValidationError, match="uppercase"):
            generate_uvx_dockerfile("pkg", "pkg", build_env={"bad_key": "val"})

    def test_validation_rejects_reserved_env_key(self):
        with pytest.raises(ValidationError, match="reserved"):
            generate_uvx_dockerfile("pkg", "pkg", build_env={"PATH": "/bad"})


class TestGenerateNpxDockerfileWithRuntimeConfig:
    """NPX Dockerfile generation with RuntimeConfig."""

    def test_default_runtime(self):
        df = generate_npx_dockerfile("@scope/my-server")
        assert "FROM node:22-alpine" in df
        assert "npm install" in df
        assert "@scope/my-server" in df
        assert "__argus_entry" in df

    def test_custom_builder_image(self):
        rc = RuntimeConfig(builder_image="node:20-alpine")
        df = generate_npx_dockerfile("my-pkg", runtime_config=rc)
        assert "FROM node:20-alpine" in df

    def test_system_deps(self):
        df = generate_npx_dockerfile("my-pkg", system_deps=["ripgrep"])
        assert "apk add --no-cache ripgrep" in df

    def test_additional_packages(self):
        rc = RuntimeConfig(
            builder_image="node:22-alpine",
            additional_packages=["curl"],
        )
        df = generate_npx_dockerfile("my-pkg", runtime_config=rc)
        assert "apk add --no-cache curl" in df

    def test_binary_discovery_heuristic(self):
        df = generate_npx_dockerfile("@scope/my-server")
        assert 'BIN_NAME="my-server"' in df

    def test_non_root_user(self):
        df = generate_npx_dockerfile("my-pkg")
        assert "nonroot" in df

    def test_validation_rejects_bad_package(self):
        with pytest.raises(ValidationError):
            generate_npx_dockerfile("b@d;pkg")

    def test_validation_rejects_bad_deps(self):
        with pytest.raises(ValidationError):
            generate_npx_dockerfile("pkg", system_deps=["$(evil)"])


class TestComputeImageTag:
    """Image tag computation."""

    def test_deterministic(self):
        df = "FROM python:3.13-slim\nRUN pip install uv"
        tag1 = compute_image_tag("uvx", "my-pkg", df)
        tag2 = compute_image_tag("uvx", "my-pkg", df)
        assert tag1 == tag2

    def test_different_content(self):
        tag1 = compute_image_tag("uvx", "pkg", "content-a")
        tag2 = compute_image_tag("uvx", "pkg", "content-b")
        assert tag1 != tag2

    def test_format(self):
        tag = compute_image_tag("uvx", "my-pkg", "content")
        assert tag.startswith(f"{IMAGE_PREFIX}/")

    def test_scoped_package_sanitised(self):
        tag = compute_image_tag("npx", "@scope/pkg", "content")
        name_part = tag.split("/", 1)[1].split(":")[0]
        assert "@" not in name_part
        assert "/" not in name_part


# Public API re-exports (__init__.py) ─────────────────────────────────


class TestPublicAPI:
    """Verify backwards-compatible public API from the package __init__."""

    def test_runtime_config_importable(self):
        from argus_mcp.bridge.container.templates import RuntimeConfig

        assert RuntimeConfig is not None

    def test_template_data_importable(self):
        from argus_mcp.bridge.container.templates import TemplateData

        assert TemplateData is not None

    def test_validation_importable(self):
        from argus_mcp.bridge.container.templates import (
            ValidationError,
            validate_build_env_key,
            validate_build_env_value,
            validate_package_name,
            validate_system_deps,
        )

        assert all(
            [
                ValidationError,
                validate_build_env_key,
                validate_build_env_value,
                validate_package_name,
                validate_system_deps,
            ]
        )

    def test_generators_importable(self):
        from argus_mcp.bridge.container.templates import (
            IMAGE_PREFIX,
            compute_image_tag,
            generate_npx_dockerfile,
            generate_uvx_dockerfile,
            parse_npx_args,
            parse_uvx_args,
        )

        assert all(
            [
                IMAGE_PREFIX,
                compute_image_tag,
                generate_npx_dockerfile,
                generate_uvx_dockerfile,
                parse_npx_args,
                parse_uvx_args,
            ]
        )

    def test_go_generators_importable(self):
        from argus_mcp.bridge.container.templates import (
            generate_go_dockerfile,
            parse_go_args,
        )

        assert all([generate_go_dockerfile, parse_go_args])

    def test_render_template_importable(self):
        from argus_mcp.bridge.container.templates import render_template

        assert callable(render_template)


# Go transport: RuntimeConfig ─────────────────────────────────────────


class TestRuntimeConfigGo:
    """RuntimeConfig for Go transport."""

    def test_go_defaults_present(self):
        assert "go" in RUNTIME_DEFAULTS
        assert "builder_image" in RUNTIME_DEFAULTS["go"]

    def test_go_default_image(self):
        assert RUNTIME_DEFAULTS["go"]["builder_image"] == "golang:1.24-alpine"

    def test_go_default_packages(self):
        assert RUNTIME_DEFAULTS["go"]["additional_packages"] == [
            "ca-certificates",
            "git",
        ]

    def test_for_go_defaults(self):
        rc = RuntimeConfig.for_transport("go")
        assert rc.builder_image == "golang:1.24-alpine"
        assert rc.additional_packages == ["ca-certificates", "git"]

    def test_go_override_builder_image(self):
        rc = RuntimeConfig.for_transport(
            "go",
            overrides={"builder_image": "golang:1.23-alpine"},
        )
        assert rc.builder_image == "golang:1.23-alpine"
        assert rc.additional_packages == ["ca-certificates", "git"]

    def test_go_override_packages(self):
        rc = RuntimeConfig.for_transport(
            "go",
            overrides={"additional_packages": ["curl"]},
        )
        assert rc.additional_packages == ["curl"]


# Go transport: parse_go_args ─────────────────────────────────────────

from argus_mcp.bridge.container.templates._generators import (
    _strip_go_version,
    parse_go_args,
)


class TestParseGoArgs:
    """parse_go_args argument parsing."""

    def test_basic_module_path(self):
        module, args = parse_go_args([], go_package="github.com/user/repo")
        assert module == "github.com/user/repo"
        assert args == []

    def test_module_with_version(self):
        module, args = parse_go_args(
            [],
            go_package="github.com/user/repo@v1.2.3",
        )
        assert module == "github.com/user/repo@v1.2.3"
        assert args == []

    def test_passthrough_args(self):
        module, args = parse_go_args(
            ["--kubeconfig", "/etc/kube"],
            go_package="github.com/user/repo",
        )
        assert module == "github.com/user/repo"
        assert args == ["--kubeconfig", "/etc/kube"]

    def test_requires_go_package(self):
        with pytest.raises(ValueError, match="go_package"):
            parse_go_args([])

    def test_empty_go_package_raises(self):
        with pytest.raises(ValueError, match="go_package"):
            parse_go_args([], go_package="")

    def test_whitespace_go_package_raises(self):
        with pytest.raises(ValueError, match="go_package"):
            parse_go_args([], go_package="   ")


class TestStripGoVersion:
    """_strip_go_version helper."""

    def test_strips_at_latest(self):
        assert _strip_go_version("github.com/user/repo@latest") == "github.com/user/repo"

    def test_strips_at_semver(self):
        assert _strip_go_version("github.com/user/repo@v1.2.3") == "github.com/user/repo"

    def test_no_version(self):
        assert _strip_go_version("github.com/user/repo") == "github.com/user/repo"

    def test_preserves_dotted_paths(self):
        assert _strip_go_version("github.com/user/repo.v2") == "github.com/user/repo.v2"


# Go transport: generate_go_dockerfile ────────────────────────────────

from argus_mcp.bridge.container.templates import generate_go_dockerfile


class TestGenerateGoDockerfile:
    """go.dockerfile.j2 template generation."""

    def test_basic_output(self):
        df = generate_go_dockerfile(go_package="github.com/user/repo")
        assert "FROM golang:1.24-alpine AS builder" in df
        assert "go install" in df
        assert "github.com/user/repo" in df
        assert "ENTRYPOINT" in df
        assert "/app/mcp-server" in df

    def test_multi_stage_build(self):
        df = generate_go_dockerfile(go_package="github.com/user/repo")
        assert df.count("FROM") >= 2  # builder + runtime stages

    def test_cgo_disabled(self):
        df = generate_go_dockerfile(go_package="github.com/user/repo")
        assert "CGO_ENABLED=0" in df

    def test_static_linux_build(self):
        df = generate_go_dockerfile(go_package="github.com/user/repo")
        assert "GOOS=linux" in df

    def test_non_root_user(self):
        df = generate_go_dockerfile(go_package="github.com/user/repo")
        assert "nonroot" in df or "USER" in df

    def test_custom_builder_image(self):
        rc = RuntimeConfig(
            builder_image="golang:1.23-alpine",
            additional_packages=[],
        )
        df = generate_go_dockerfile(
            go_package="github.com/user/repo",
            runtime_config=rc,
        )
        assert "FROM golang:1.23-alpine AS builder" in df

    def test_system_deps(self):
        df = generate_go_dockerfile(
            go_package="github.com/user/repo",
            system_deps=["curl", "jq"],
        )
        assert "curl" in df
        assert "jq" in df

    def test_additional_packages(self):
        rc = RuntimeConfig(
            builder_image="golang:1.24-alpine",
            additional_packages=["wget", "vim"],
        )
        df = generate_go_dockerfile(
            go_package="github.com/user/repo",
            runtime_config=rc,
        )
        assert "wget" in df
        assert "vim" in df

    def test_versioned_module_path(self):
        df = generate_go_dockerfile(
            go_package="github.com/user/repo@v2.0.0",
        )
        assert "github.com/user/repo@v2.0.0" in df

    def test_auto_appends_latest(self):
        """Unversioned modules get @latest appended at build time via shell logic."""
        df = generate_go_dockerfile(
            go_package="github.com/user/repo",
        )
        # The template uses a shell if-statement to append @latest at build time
        # when no @version is present in the package specifier.
        assert "@latest" in df  # shell logic present
        # Versioned specifier should appear as-is (no double-version)
        df2 = generate_go_dockerfile(
            go_package="github.com/user/repo@v1.0.0",
        )
        assert "github.com/user/repo@v1.0.0" in df2

    def test_empty_package_raises(self):
        with pytest.raises((ValueError, Exception)):
            generate_go_dockerfile(go_package="")

    def test_header_comment(self):
        df = generate_go_dockerfile(go_package="github.com/user/repo")
        assert df.startswith("# Auto-generated")

    def test_no_shell_injection_in_package(self):
        """Injection attempts in go_package should be rejected."""
        with pytest.raises((ValueError, Exception)):
            generate_go_dockerfile(go_package="pkg; rm -rf /")

    def test_deterministic_output(self):
        df1 = generate_go_dockerfile(go_package="github.com/user/repo")
        df2 = generate_go_dockerfile(go_package="github.com/user/repo")
        assert df1 == df2


# Go transport: compute_image_tag ─────────────────────────────────────


class TestComputeImageTagGo:
    """Image tag computation for Go transport."""

    def test_go_tag_format(self):
        df = generate_go_dockerfile(go_package="github.com/strowk/mcp-k8s-go")
        tag = compute_image_tag("go", "github.com/strowk/mcp-k8s-go", df)
        assert tag.startswith(f"{IMAGE_PREFIX}/")
        assert "go-" in tag

    def test_go_tag_deterministic(self):
        df = generate_go_dockerfile(go_package="github.com/user/repo")
        tag1 = compute_image_tag("go", "github.com/user/repo", df)
        tag2 = compute_image_tag("go", "github.com/user/repo", df)
        assert tag1 == tag2

    def test_go_tag_different_packages(self):
        df1 = generate_go_dockerfile(go_package="github.com/user/repo-a")
        df2 = generate_go_dockerfile(go_package="github.com/user/repo-b")
        tag1 = compute_image_tag("go", "github.com/user/repo-a", df1)
        tag2 = compute_image_tag("go", "github.com/user/repo-b", df2)
        assert tag1 != tag2

    def test_go_tag_sanitised_slashes(self):
        """Slashes in Go module paths should be sanitised in the tag."""
        df = generate_go_dockerfile(go_package="github.com/strowk/mcp-k8s-go")
        tag = compute_image_tag("go", "github.com/strowk/mcp-k8s-go", df)
        # The repo portion of the tag (between / and :) should not have slashes
        repo_part = tag.split("/", 1)[1].split(":")[0]
        assert "/" not in repo_part


# Go transport: image_builder integration ─────────────────────────────

from argus_mcp.bridge.container.image_builder import classify_command


class TestClassifyCommandGo:
    """classify_command with Go entries."""

    def test_go_command(self):
        assert classify_command("go") == "go"

    def test_go_path(self):
        assert classify_command("/usr/local/bin/go") == "go"

    def test_unknown_binary(self):
        assert classify_command("mcp-k8s") is None

    def test_still_detects_uvx(self):
        assert classify_command("uvx") == "uvx"

    def test_still_detects_npx(self):
        assert classify_command("npx") == "npx"


# Go transport: schema_backends ───────────────────────────────────────

from argus_mcp.config.schema_backends import ContainerConfig


class TestContainerConfigGoFields:
    """ContainerConfig Go-related fields."""

    def test_transport_field_default(self):
        cc = ContainerConfig()
        assert cc.transport is None

    def test_go_package_field_default(self):
        cc = ContainerConfig()
        assert cc.go_package is None

    def test_go_transport_valid(self):
        cc = ContainerConfig(transport="go", go_package="github.com/user/repo")
        assert cc.transport == "go"
        assert cc.go_package == "github.com/user/repo"

    def test_uvx_transport_valid(self):
        cc = ContainerConfig(transport="uvx")
        assert cc.transport == "uvx"

    def test_npx_transport_valid(self):
        cc = ContainerConfig(transport="npx")
        assert cc.transport == "npx"

    def test_invalid_transport_rejects(self):
        with pytest.raises(Exception):
            ContainerConfig(transport="rust")

    def test_transport_normalised_lowercase(self):
        cc = ContainerConfig(transport="GO")
        assert cc.transport == "go"
