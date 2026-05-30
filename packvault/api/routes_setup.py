from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from packvault.api.deps import get_optional_session, get_state
from packvault.api.error_handling import UI_FORM_ERROR_MESSAGES
from packvault.auth.bootstrap import is_bootstrap_admin
from packvault.auth.permissions import SessionUser
from packvault.runtime import AppState
from packvault.setup.service import check_database_connection, initialize_system
from packvault.ui.templates_ctx import templates
from packvault.utils.errors import ConflictError, ForbiddenError, ServiceUnavailableError

router = APIRouter(tags=["setup"])


async def _database_status(state: AppState) -> tuple[bool, str]:
    if not state.database.enabled:
        return False, "Database URL is not configured."

    try:
        async with state.database.session() as session:
            status = await check_database_connection(session)
            return status.reachable, status.detail
    except Exception as exc:
        return False, str(exc)


def _encryption_context(state: AppState) -> dict:
    secrets = state.settings.secrets
    encryption = state.encryption

    context: dict = {
        "encrypt_at_rest": secrets.encrypt_at_rest,
        "provider": None,
        "provider_detail": None,
        "endpoint": None,
        "key_ready": True,
    }

    if not secrets.encrypt_at_rest:
        return context

    context["provider"] = encryption.provider
    if encryption.provider == "environment":
        variable = secrets.encryption_key.environment.variable
        import os

        context["provider_detail"] = variable
        context["key_ready"] = bool(os.environ.get(variable, "").strip())
    elif encryption.provider == "aws_secrets_manager":
        aws = secrets.encryption_key.aws_secrets_manager
        context["provider_detail"] = aws.secret_id
        if aws.endpoint_url:
            context["endpoint"] = aws.endpoint_url
        context["key_ready"] = encryption.key is not None

    return context


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        return RedirectResponse("/login", status_code=302)

    if state.system_initialized:
        return templates.TemplateResponse(
            request,
            "setup_complete.html",
            {},
        )

    if not is_bootstrap_admin(user, state.settings):
        raise ForbiddenError("Only the bootstrap platform admin can run setup")

    db_reachable, db_detail = await _database_status(state)
    success = request.query_params.get("success") == "1"
    error_code = request.query_params.get("error")
    error_message = UI_FORM_ERROR_MESSAGES.get(error_code) if error_code else None
    reference_id = request.query_params.get("ref")

    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "user": user,
            "database_configured": state.database.enabled,
            "database_reachable": db_reachable,
            "database_detail": db_detail,
            "encryption": _encryption_context(state),
            "token_count": len(state.settings.auth.tokens),
            "success": success,
            "error_message": error_message,
            "reference_id": reference_id,
        },
    )


@router.post("/admin/setup/initialize")
async def setup_initialize(
    request: Request,
    user: SessionUser | None = Depends(get_optional_session),
    state: AppState = Depends(get_state),
):
    if user is None:
        raise ForbiddenError("Sign in is required to initialize PackVault")

    if not is_bootstrap_admin(user, state.settings):
        raise ForbiddenError("Only the bootstrap platform admin can run setup")

    if state.system_initialized:
        raise ConflictError("PackVault is already initialized")

    if not state.database.enabled:
        raise ServiceUnavailableError("Database URL is not configured")

    db_reachable, db_detail = await _database_status(state)
    if not db_reachable:
        raise ServiceUnavailableError(f"Database is not reachable: {db_detail}")

    if state.encryption.enabled and state.encryption.key is None:
        raise ServiceUnavailableError(
            "Encryption is enabled but the master key is not available"
        )

    async with state.database.session() as session:
        await initialize_system(
            session,
            settings=state.settings,
            protector=state.secret_protector,
            initialized_by=user.subject,
        )

    state.system_initialized = True

    wants_json = "application/json" in request.headers.get("accept", "").lower()
    if wants_json:
        return JSONResponse(
            status_code=200,
            content={
                "status": "initialized",
                "initialized_by": user.subject,
            },
        )

    return RedirectResponse("/dashboard?setup=complete", status_code=303)
