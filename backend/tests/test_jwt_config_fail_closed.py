"""Isolated Settings/JWT tests: no dotenv files, app startup, DB or network."""
import ast
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from pydantic import ValidationError
from jose import jwt, JWTError

ROOT = Path(__file__).resolve().parents[1]
SYNTHETIC = "unit-only-external-signing-key-0123456789abcdef"


def settings_module():
    tree = ast.parse((ROOT / "app/core/config.py").read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "settings" for t in n.targets))]
    mod = types.ModuleType("isolated_jwt_config")
    mod.__file__ = str(ROOT / "app/core/config.py")
    exec(compile(tree, mod.__file__, "exec"), mod.__dict__)
    return mod


class JwtConfigTests(unittest.TestCase):
    def build(self, value=None, **kwargs):
        env = {} if value is None else {"JWT_SECRET": value}
        with patch.dict(os.environ, env, clear=True):
            return settings_module().Settings(_env_file=None, **kwargs)

    def test_valid_external_env_key_accepted(self):
        self.assertEqual(self.build(SYNTHETIC).jwt_secret, SYNTHETIC)

    def test_missing_key_rejected(self):
        with self.assertRaisesRegex(ValidationError, "JWT_SECRET must be externally configured"):
            self.build()

    def test_blank_key_rejected(self):
        for value in ("", " ", "\t\n"):
            with self.subTest(kind="blank"), self.assertRaises(ValidationError):
                self.build(value)

    def test_retired_fingerprint_rejected_without_disclosure(self):
        # Exercise the denial branch with synthetic input, not a copied credential.
        tree = ast.parse((ROOT / "app/core/config.py").read_text())
        validator = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                         and n.name == "require_external_jwt_secret")
        fingerprint = next(n.value for n in ast.walk(validator)
                           if isinstance(n, ast.Constant) and isinstance(n.value, str)
                           and len(n.value) == 64 and all(c in "0123456789abcdef" for c in n.value))
        mod = settings_module()
        with patch.dict(os.environ, {}, clear=True), patch.object(mod.hashlib, "sha256",
                return_value=types.SimpleNamespace(hexdigest=lambda:fingerprint)):
            with self.assertRaises(ValidationError) as caught:
                mod.Settings(_env_file=None, jwt_secret=SYNTHETIC)
        self.assertNotIn(SYNTHETIC, str(caught.exception))

    def test_valid_key_bytes_preserved_not_rotated_or_trimmed(self):
        value = " " + SYNTHETIC + " "
        self.assertEqual(self.build(value).jwt_secret, value)
        self.assertEqual(self.build(SYNTHETIC).jwt_algorithm, "HS256")
        self.assertEqual(self.build(SYNTHETIC).jwt_expires_minutes, 15)
        self.assertEqual(self.build(SYNTHETIC).jwt_refresh_expires_days, 30)

    def test_settings_repr_and_validation_text_hide_input(self):
        self.assertNotIn(SYNTHETIC, repr(self.build(SYNTHETIC)))
        with self.assertRaises(ValidationError) as caught:
            self.build(SYNTHETIC, jwt_expires_minutes=SYNTHETIC)
        self.assertNotIn(SYNTHETIC, str(caught.exception))

    def test_actual_security_uses_external_key_for_access_and_refresh(self):
        cfg = types.ModuleType("app.core.config")
        cfg.settings = self.build(SYNTHETIC)
        module = types.ModuleType("isolated_security")
        with patch.dict(sys.modules, {"app.core.config": cfg}):
            exec(compile((ROOT / "app/core/security.py").read_text(), "security.py", "exec"), module.__dict__)
        self.assertEqual(module.SECRET_KEY, SYNTHETIC)
        claims = {"sub": "synthetic-user", "sid": "synthetic-session"}
        access = module.create_access_token(claims)
        refresh = module.create_refresh_token(claims)
        self.assertEqual(jwt.decode(access, SYNTHETIC, algorithms=["HS256"])["sub"], claims["sub"])
        self.assertEqual(module.decode_refresh_token(refresh)["sid"], claims["sid"])
        with self.assertRaises(JWTError):
            jwt.decode(access, "different-unit-key", algorithms=["HS256"])

    def test_startup_still_constructs_cached_settings(self):
        tree = ast.parse((ROOT / "app/core/config.py").read_text())
        singleton = next(n for n in tree.body if isinstance(n, ast.Assign)
                         and any(isinstance(t, ast.Name) and t.id == "settings" for t in n.targets))
        self.assertEqual(ast.unparse(singleton.value), "get_settings()")
        mod = settings_module()
        mod.Settings.model_config["env_file"] = None
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValidationError):
            mod.get_settings()


if __name__ == "__main__":
    with patch("socket.socket.connect", side_effect=AssertionError("Network forbidden")):
        unittest.main(verbosity=2)
