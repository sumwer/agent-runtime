FROM python:3.12-slim
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir pandas==2.2.2 numpy==1.26.4 matplotlib==3.8.4 scipy==1.11.4 \
    && python -m pip uninstall -y pip
ENV MPLCONFIGDIR=/tmp/mpl PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
CMD ["python"]
