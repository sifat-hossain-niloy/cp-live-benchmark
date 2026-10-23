# Immutable multi-platform manifest; image ID and platform are also recorded at runtime.
FROM python:3.11.11-bookworm@sha256:4ca910a51a1a474e5d95aa52455331b2a94272eeae3c498be1ad7a2ff9b00bf3
# This digest already contains GCC 12.2.0. Fail the build if toolchains drift.
RUN test "$(g++ -dumpfullversion)" = "12.2.0" && test "$(python3 -c 'import platform; print(platform.python_version())')" = "3.11.11"
COPY runner.py /opt/cflive/runner.py
RUN chmod 0555 /opt/cflive/runner.py && mkdir /input /artifact && chmod 0555 /input /artifact
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 LC_ALL=C.UTF-8
USER 65534:65534
WORKDIR /work
ENTRYPOINT ["python3", "-I", "/opt/cflive/runner.py"]
