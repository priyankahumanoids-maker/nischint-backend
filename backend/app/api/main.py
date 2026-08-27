# Main API Router
from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.seniors import router as seniors_router
from app.api.medicine import router as medicine_router
from app.api.devices import router as devices_router
from app.api.telemetry import router as telemetry_router
from app.api.incidents import router as incidents_router
from app.api.dashboard import router as dashboard_router
from app.api.device_telemetry import router as device_telemetry_router
from app.api.stream import router as stream_router
from app.api.push import router as push_router
from app.api.alert_ack import router as alert_ack_router
from app.api.safety_incidents import router as safety_incidents_router
from app.api.incidents_feed import router as incidents_feed_router
from app.api.incident_feedback import router as incident_feedback_router
from app.api.guardian_impact import router as guardian_impact_router
from app.api.streaming import router as streaming_router
from app.api.journey import router as journey_router
from app.api.operator import router as operator_router
from app.api.my import router as my_router
from app.api.safety import router as safety_router
from app.api.night_guardian import router as night_guardian_router
from app.api.safe_route import router as safe_route_router
from app.api.guardian import router as guardian_router
from app.api.predictive_alert import router as predictive_alert_router
from app.api._dev import router as _dev_router
from app.api.guardian_dashboard import router as guardian_dashboard_router
from app.api.safety_score import router as safety_score_router
from app.api.emergency import router as emergency_router
from app.api.route_monitor import router as route_monitor_router
from app.api.sensors import router as sensors_router
from app.api.zones import router as zones_router
from app.api.geofence import router as geofence_router
from app.api.pickup import router as pickup_router
from app.api.safety_brain import router as safety_brain_router
from app.api.reroute import router as reroute_router
from app.api.safety_brain_v2 import router as safety_brain_v2_router
from app.api.fake_call import router as fake_call_router
from app.api.fake_notification import router as fake_notification_router
from app.api.sos import router as sos_router
from app.api.guardian_ai import router as guardian_ai_router
from app.api.voice_trigger import router as voice_trigger_router
from app.api.google_auth import router as google_auth_router
from app.api.admin import router as admin_router
from app.api.monitoring import router as monitoring_router
from app.api.public_status import router as public_status_router
from app.api.ai_confidence import router as ai_confidence_router
from app.api.caregiver import router as caregiver_router
from app.api.replay import router as replay_router
from app.api.guardian_ai_v2 import router as guardian_ai_v2_router
from app.api.guardian_network import router as guardian_network_router
from app.api.safety_events import router as safety_events_router
from app.api.realtime_events import router as realtime_events_router
from app.api.device import router as device_router
from app.api.guardian_live import router as guardian_live_router
from app.api.guardian_incidents import router as guardian_incidents_router
from app.api.demo import router as demo_router
from app.api.pilot import router as pilot_router
from app.api.status import router as status_router
from app.api.chatbot import router as chatbot_router
from app.api.notification_settings import router as notif_settings_router
from app.api.ai_learning import router as ai_learning_router
from app.api.checkin import router as checkin_router
from app.api.ws_command_center import router as ws_command_center_router
from app.api.ai_services import router as ai_services_router
from app.api.location_sharing import router as location_sharing_router
from app.api.child import router as child_router
from app.api.guardian_link import router as guardian_link_router
from app.api.twilio_webhook import router as twilio_webhook_router
from app.api.revenue_os import router as revenue_os_router
from app.api.wearable import router as wearable_router
from app.api.funnel_tracking import router as funnel_tracking_router
from app.api.pr_intelligence import router as pr_intelligence_router
from app.api.blog import router as blog_router
from app.api.rag import rag_router, blog_rag_router, knowledge_router
from app.api.geo_analytics import router as geo_analytics_router
from app.api.geo_scaling import router as geo_scaling_router
from app.api.entity_engine import router as entity_engine_router
from app.api.seo_engine import router as seo_engine_router
from app.api.journey_sync import router as journey_sync_router
from app.api.journey_rollout import router as journey_rollout_router
from app.api.ai_brain import router as ai_brain_router
from app.api.command_center_unified import router as command_center_unified_router
from app.api.command_center_unified import operator_extra_router as command_center_extra_router
from app.api.risk_panel import router as risk_panel_router
from app.api.risk import router as risk_router
from app.api.behavioral import router as behavioral_router
from app.api.motion_features import router as motion_features_router
from app.api.signals_motion import router as signals_motion_router
from app.api.env_hazards import router as env_hazards_router
from app.api.operator_dev import router as operator_dev_router
from app.api.sf02_bench import router as sf02_bench_router
from app.api.privacy import router as privacy_router
from app.api.erasure import router as erasure_router, admin_router as erasure_admin_router
from app.api.consents import router as consents_router, admin_router as consents_admin_router
from app.api.db_rescue import router as db_rescue_router
from app.api.dpo import router as dpo_router
from app.api.health_signals import router as health_signals_router
from app.api.sb01_hermes import admin_router as sb01_admin_router, feedback_router as sb01_feedback_router
from app.api.emergency_stream import router as emergency_stream_router

api_router = APIRouter()

api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(seniors_router)
api_router.include_router(medicine_router)
api_router.include_router(devices_router)
api_router.include_router(telemetry_router)
api_router.include_router(incidents_router)
api_router.include_router(dashboard_router)
api_router.include_router(device_telemetry_router)
api_router.include_router(stream_router)
api_router.include_router(push_router)
api_router.include_router(alert_ack_router)
api_router.include_router(safety_incidents_router)
api_router.include_router(incidents_feed_router)
api_router.include_router(incident_feedback_router)
api_router.include_router(guardian_impact_router)
api_router.include_router(streaming_router)
api_router.include_router(risk_panel_router)
api_router.include_router(risk_router)
api_router.include_router(behavioral_router)
api_router.include_router(motion_features_router)
api_router.include_router(signals_motion_router)
api_router.include_router(env_hazards_router)
api_router.include_router(operator_dev_router)
api_router.include_router(sf02_bench_router)
api_router.include_router(privacy_router)
# DPDP-01 self-serve erasure (user + admin endpoints)
api_router.include_router(erasure_router)
api_router.include_router(erasure_admin_router)
# DPDP-04 separately-revocable consent capture
api_router.include_router(consents_router)
# DPDP-04 admin audit endpoint
api_router.include_router(consents_admin_router)
api_router.include_router(db_rescue_router)
# DPDP-05 DPO contact surface (/api/dpo + /api/dpo.json)
api_router.include_router(dpo_router)
api_router.include_router(health_signals_router)
api_router.include_router(sb01_admin_router)
api_router.include_router(sb01_feedback_router)
api_router.include_router(emergency_stream_router)
api_router.include_router(journey_router)
api_router.include_router(operator_router)
api_router.include_router(my_router)
api_router.include_router(safety_router)
api_router.include_router(night_guardian_router)
api_router.include_router(safe_route_router)
api_router.include_router(guardian_router)
api_router.include_router(predictive_alert_router)
api_router.include_router(guardian_dashboard_router)
api_router.include_router(safety_score_router)
api_router.include_router(emergency_router)
api_router.include_router(route_monitor_router)
api_router.include_router(sensors_router)
api_router.include_router(zones_router)
api_router.include_router(geofence_router)
api_router.include_router(pickup_router)
api_router.include_router(safety_brain_router)
api_router.include_router(reroute_router)
api_router.include_router(safety_brain_v2_router)
api_router.include_router(fake_call_router)
api_router.include_router(fake_notification_router)
api_router.include_router(sos_router)
api_router.include_router(guardian_ai_router)
api_router.include_router(voice_trigger_router)
api_router.include_router(google_auth_router)
api_router.include_router(admin_router)
api_router.include_router(monitoring_router)
api_router.include_router(public_status_router)
api_router.include_router(ai_confidence_router)
api_router.include_router(caregiver_router)
api_router.include_router(replay_router)
api_router.include_router(guardian_ai_v2_router)
api_router.include_router(guardian_network_router)
api_router.include_router(safety_events_router)
api_router.include_router(realtime_events_router)
api_router.include_router(device_router)
api_router.include_router(guardian_live_router)
api_router.include_router(guardian_incidents_router)
api_router.include_router(demo_router)
api_router.include_router(pilot_router)
api_router.include_router(status_router)
api_router.include_router(chatbot_router)
api_router.include_router(notif_settings_router)
api_router.include_router(ai_learning_router)
api_router.include_router(checkin_router)
api_router.include_router(ws_command_center_router)
api_router.include_router(ai_services_router)
api_router.include_router(location_sharing_router)
api_router.include_router(child_router)
api_router.include_router(guardian_link_router)
api_router.include_router(revenue_os_router)
api_router.include_router(wearable_router)
api_router.include_router(funnel_tracking_router)
api_router.include_router(pr_intelligence_router)
api_router.include_router(blog_router)
api_router.include_router(rag_router)
api_router.include_router(blog_rag_router)
api_router.include_router(knowledge_router)
api_router.include_router(twilio_webhook_router)
api_router.include_router(health_router)
api_router.include_router(geo_analytics_router)
api_router.include_router(geo_scaling_router)
api_router.include_router(entity_engine_router)
api_router.include_router(seo_engine_router)
api_router.include_router(journey_sync_router)
api_router.include_router(journey_rollout_router)
api_router.include_router(ai_brain_router)
api_router.include_router(command_center_unified_router)
api_router.include_router(command_center_extra_router)
api_router.include_router(_dev_router)
