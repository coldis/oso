import logging
import os.path

from django.apps import apps
from django.http import HttpRequest
from django.db.models.manager import Manager


from oso import Oso as _Oso
from polar.exceptions import DuplicateClassAliasError
from polar.partial import Partial, TypeConstraint, InConstraint


_logger = logging.getLogger(__name__)

Oso = _Oso()
"""Singleton :py:class:`oso.Oso` instance.

Use for loading policy files and registering classes.
"""


def polar_model_name(model):
    app_name = model._meta.app_label
    app_namespace = app_name.replace(".", "::")
    return f"{app_namespace}::{model.__name__}"


def django_model_name(polar_name: str):
    return polar_name.replace("::", ".")


def init_oso():
    def manager_to_partial(maybe_manager, host):
        if isinstance(maybe_manager, Manager):
            id = Oso.ffi_polar.new_id()
            # TODO(gj): try In(Isa(_this, Post), _this)
            return Partial(
                f"_manager_partial_{id}",
                InConstraint(host.to_polar(maybe_manager.all())),
                TypeConstraint(
                    polar_model_name(maybe_manager.target_field.related_model)
                ),
            )

    Oso.host.to_polar_hooks.append(manager_to_partial)

    def register_class(model, name=None):
        try:
            Oso.register_class(model, name=name)
        except DuplicateClassAliasError:
            pass

    # Register all models.
    for app in apps.get_app_configs():
        for model in app.get_models():
            register_class(model, polar_model_name(model))

    # Custom registration for auth (AnonymousUser)
    if apps.is_installed("django.contrib.auth"):
        from django.contrib.auth.models import AnonymousUser

        # Register under `auth` app_label to match default User model, but also fully-qualified name
        register_class(AnonymousUser, "auth::AnonymousUser")
        register_class(AnonymousUser, "django::contrib::auth::AnonymousUser")

    # Register request
    register_class(HttpRequest)

    return load_policy_files()


def load_policy_files():
    loaded_files = []

    # Load all polar files in each app's "policy" directory.
    for app in apps.get_app_configs():
        policy_dir = os.path.join(app.path, "policy")
        for path, _, filenames in os.walk(policy_dir):
            for file in filenames:
                file_path = os.path.join(path, file)
                if os.path.splitext(file)[1] == ".polar":
                    Oso.load_file(file_path)
                    loaded_files.append(file_path)

    _logger.debug(f"Loaded policies: {loaded_files}")

    return loaded_files


def reset_oso():
    Oso.clear_rules()
    load_policy_files()
