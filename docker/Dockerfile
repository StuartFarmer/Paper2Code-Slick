FROM python:3.11-slim@sha256:e88e9763f943ec1834f992a4b51e0f24500486803e8bc534e5767af9ea65f6ce
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY docker/requirements.lock /runner/requirements.lock
RUN pip install --require-hashes --only-binary=:all: -r /runner/requirements.lock \
    && python -c "import numpy, pandas, scipy, yaml, pytest, hypothesis, torch; assert torch.version.cuda is None"
COPY docker/check.py docker/pytest.ini /runner/
USER 65534:65534
WORKDIR /workspace
