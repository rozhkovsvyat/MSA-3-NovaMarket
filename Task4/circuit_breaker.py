"""Проверка Circuit Breaker на NGINX-прокси.

Первые 60 секунд логистика сломана: /slow отвечает дольше тайм-аута, /error — 503
(режим задаёт LOGISTICS_FAILURE). После пяти неудач прокси сразу отдаёт fallback,
не обращаясь к логистике. Пробный запрос через 30 секунд тоже падает, и цепь остаётся
разомкнутой. Потом логистика отвечает (/fast), и вызовы восстанавливаются.
По заголовку X-Upstream видно, ходил ли прокси в логистику (127.0.0.1:9090).

Сценарий рассчитан на одного пользователя, чтобы запросы шли по очереди:
locust -f circuit_breaker.py --host=http://localhost:8080 --headless -u 1 -r 1 -t 100s
"""

import os
import time

from locust import HttpUser, constant, events, task

BROKEN_SECONDS = 60
FAILURE_MODE = os.getenv("LOGISTICS_FAILURE", "slow")
LOGISTICS_ADDRESS = "127.0.0.1:9090"

if FAILURE_MODE not in ("slow", "error"):
    raise SystemExit(f"LOGISTICS_FAILURE must be slow or error, got {FAILURE_MODE!r}")

run = {}


def log(message):
    print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)


@events.test_start.add_listener
def on_test_start(**_):
    run.update(started_at=time.monotonic(), failures_in_row=0, circuit_open=False,
               opened_after=None, restored=False)


@events.quitting.add_listener
def on_quitting(environment, **_):
    passed = run.get("opened_after") == 5 and run.get("restored")
    log("Check passed: circuit opened after 5 failures, then calls were restored" if passed
        else "Check failed: circuit did not open after 5 failures or calls were not restored")
    environment.process_exit_code = 0 if passed else 1


def is_fallback(response):
    return (response.status_code == 503
            and response.headers.get("Retry-After") == "30"
            and '"fallback"' in response.text)


class LogisticsClient(HttpUser):
    wait_time = constant(1)

    def on_start(self):
        log("Starting Circuit Breaker test...")

    @task
    def tracking(self):
        broken = time.monotonic() - run["started_at"] < BROKEN_SECONDS
        path = f"/logistics/{FAILURE_MODE}" if broken else "/logistics/fast"
        name = "logistics broken" if broken else "logistics ok"

        with self.client.get(path, name=name, catch_response=True) as response:
            called_logistics = LOGISTICS_ADDRESS in response.headers.get("X-Upstream", "")
            seconds = response.elapsed.total_seconds()

            if response.status_code == 200 and called_logistics and not broken:
                response.success()
                run["failures_in_row"] = 0
                if run["circuit_open"]:
                    run.update(circuit_open=False, restored=True)
                    log("Logistics answers again: Circuit Breaker closed, calls restored")
            elif is_fallback(response) and called_logistics:
                run["failures_in_row"] += 1
                response.failure(f"logistics failed, fallback after {seconds:.1f} s")
                if run["circuit_open"]:
                    log("Probe call after the pause failed: Circuit Breaker stays open")
                else:
                    log(f"Logistics call failed ({run['failures_in_row']}), fallback after {seconds:.1f} s")
            elif is_fallback(response):
                response.failure("circuit open: fallback without calling logistics")
                if not run["circuit_open"]:
                    run.update(circuit_open=True, opened_after=run["failures_in_row"])
                    log(f"Circuit Breaker activated after {run['failures_in_row']} failed calls: "
                        f"fallback in {seconds * 1000:.0f} ms without calling logistics")
            else:
                response.failure(f"unexpected response {response.status_code}")
                log(f"Unexpected response {response.status_code} on {path}")
