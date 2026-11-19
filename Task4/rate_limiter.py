from locust import HttpUser, between, task


class ApiClient(HttpUser):
    abstract = True
    wait_time = between(0.5, 1.5)
    client_type = None

    @task
    def products(self):
        with self.client.get("/api/products", headers={"Client-Type": self.client_type},
                             name=f"{self.client_type} /api/products", catch_response=True) as response:
            if response.status_code == 429:
                if response.headers.get("Retry-After") == "1" and "too_many_requests" in response.text:
                    response.failure("429 Too Many Requests")
                else:
                    response.failure("429 without Retry-After or JSON body")
            elif response.status_code != 200:
                response.failure(f"unexpected status {response.status_code}")


class WebClient(ApiClient):
    """80 пользователей, в среднем по запросу в секунду: около 80 rps с одного IP при лимите 50."""

    fixed_count = 80
    client_type = "web"


class MobileClient(ApiClient):
    """50 пользователей, в среднем по запросу в секунду: около 50 rps с одного IP при лимите 30."""

    fixed_count = 50
    client_type = "mobile"
