"""CP3 FastAPI/Uvicorn entrypoint."""

import uvicorn

from api.churn_service import DEFAULT_HOST, DEFAULT_PORT, logger
from api.fastapi_app import app


def main() -> None:
    logger.info("Starting churn FastAPI service on %s:%s", DEFAULT_HOST, DEFAULT_PORT)
    uvicorn.run(app, host=DEFAULT_HOST, port=DEFAULT_PORT, log_level="info")


if __name__ == "__main__":
    main()
