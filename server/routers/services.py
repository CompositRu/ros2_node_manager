"""REST endpoints for ROS2 services."""

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/services", tags=["services"])

# Technical services to filter out (lifecycle, parameter, action-internal)
FILTERED_SUFFIXES = (
    "/get_state",
    "/change_state",
    "/get_available_states",
    "/get_available_transitions",
    "/get_transition_graph",
    "/describe_parameters",
    "/get_parameter_types",
    "/get_parameters",
    "/list_parameters",
    "/set_parameters",
    "/set_parameters_atomically",
    "/_action/send_goal",
    "/_action/cancel_goal",
    "/_action/get_result",
)


def _is_technical_service(name: str) -> bool:
    """Check if a service is a technical/internal ROS2 service."""
    return any(name.endswith(suffix) for suffix in FILTERED_SUFFIXES)


@router.get("/list")
async def get_service_list(include_technical: bool = False):
    """Get list of all ROS2 services with types."""
    from ..main import app_state

    if not app_state.connection or not app_state.connection.connected:
        raise HTTPException(status_code=503, detail="Not connected to any server")

    try:
        services = await app_state.connection.ros2_service_list_typed()
        if not include_technical:
            services = [s for s in services if not _is_technical_service(s["name"])]
        return {"services": services, "count": len(services)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list services: {e}")


@router.get("/interface/{interface_type:path}")
async def get_interface_show(interface_type: str):
    """Get interface definition (fields) for a service type."""
    from ..main import app_state

    if not app_state.connection or not app_state.connection.connected:
        raise HTTPException(status_code=503, detail="Not connected to any server")

    try:
        raw = await app_state.connection.ros2_interface_show(interface_type)
        parts = raw.split("---")
        request_fields = parts[0].strip() if len(parts) > 0 else ""
        response_fields = parts[1].strip() if len(parts) > 1 else ""
        return {
            "type": interface_type,
            "raw": raw,
            "request_fields": request_fields,
            "response_fields": response_fields,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get interface: {e}")


class ServiceCallRequest(BaseModel):
    service_type: str
    request_yaml: str


@router.post("/call/{service_name:path}")
async def call_service(service_name: str, request: ServiceCallRequest):
    """Call a ROS2 service with given request data."""
    from ..main import app_state

    if not service_name.startswith("/"):
        service_name = "/" + service_name

    if not app_state.connection or not app_state.connection.connected:
        raise HTTPException(status_code=503, detail="Not connected to any server")

    # Validate YAML before passing to shell
    try:
        yaml.safe_load(request.request_yaml)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    try:
        output = await app_state.connection.ros2_service_call(
            service_name, request.service_type, request.request_yaml
        )
        return {
            "service": service_name,
            "success": True,
            "output": output,
        }
    except Exception as e:
        return {
            "service": service_name,
            "success": False,
            "output": str(e),
        }
