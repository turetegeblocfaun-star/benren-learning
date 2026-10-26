from fastapi import APIRouter

from app.api.v1 import (
    auth,
    contexts,
    courses,
    discovery,
    extended,
    governance,
    health,
    learning_assets,
    materials,
    plans,
    quizzes,
    system,
    tasks,
    tutor,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(system.router)
router.include_router(tasks.router)
router.include_router(auth.router)
router.include_router(courses.router)
router.include_router(discovery.router)
router.include_router(materials.router)
router.include_router(contexts.router)
router.include_router(learning_assets.router)
router.include_router(quizzes.router)
router.include_router(tutor.router)
router.include_router(plans.router)
router.include_router(governance.router)
router.include_router(extended.router)
