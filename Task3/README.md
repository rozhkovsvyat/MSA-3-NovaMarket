# Задание 3. Динамическое масштабирование

Тестовое приложение `ghcr.io/yandex-practicum/scaletestapp:latest` развёрнуто в Minikube. Сначала оно масштабируется по утилизации памяти (часть 1), затем по числу запросов в секунду на под с метрикой из Prometheus (часть 2). Нагрузку даёт Locust со сценарием [locustfile.py](locustfile.py).

## Стенд

- Minikube 1.39.0, Kubernetes 1.37.0, отдельный профиль `novamarket` (драйвер docker, containerd, 4 CPU, 6 GiB), аддон metrics-server.
- Prometheus — Helm-чарт `prometheus-community/prometheus` 29.46.0 (Prometheus 3.16.0), prometheus-adapter — чарт 5.4.0 (adapter 0.12.0).
- Locust 2.47.0 на ноутбуке. Сервис типа NodePort открыт через `minikube service scaletestapp -p novamarket --url`, поэтому запросы идут через kube-proxy и распределяются по подам. С `kubectl port-forward` вся нагрузка ушла бы в один под.

## Файлы

| Файл | Что это |
| :- | :- |
| [deployment.yaml](deployment.yaml) | Deployment: 1 реплика, память 30Mi, аннотации для Prometheus |
| [service.yaml](service.yaml) | Service для доступа к приложению |
| [hpa-memory.yaml](hpa-memory.yaml) | HPA по памяти: 80%, до 10 реплик (часть 1) |
| [hpa-rps.yaml](hpa-rps.yaml) | HPA по RPS на под — новая версия манифеста (часть 2) |
| [prometheus-values.yaml](prometheus-values.yaml) | values для установки Prometheus |
| [prometheus-adapter-values.yaml](prometheus-adapter-values.yaml) | правило адаптера: `http_requests_total` → `http_requests_per_second` |
| [locustfile.py](locustfile.py) | сценарий нагрузки |
| [results/](results/) | логи, describe HPA и подов, события, выгрузки Locust, ответ Custom Metrics API, скриншоты Prometheus |

## Как запустить

```bash
minikube start -p novamarket --cpus=4 --memory=6g
minikube addons enable metrics-server -p novamarket

# часть 1
kubectl apply -f deployment.yaml -f service.yaml -f hpa-memory.yaml
minikube service scaletestapp -p novamarket --url      # адрес для Locust
locust -f locustfile.py -H <адрес>                      # http://localhost:8089

# метрики раз в 15 секунд вместо 60 (вторая попытка части 1 и часть 2)
kubectl -n kube-system patch deploy metrics-server --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--metric-resolution=15s"}]'

# часть 2
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/prometheus --version 29.46.0 -n monitoring --create-namespace -f prometheus-values.yaml
helm install prometheus-adapter prometheus-community/prometheus-adapter --version 5.4.0 -n monitoring -f prometheus-adapter-values.yaml
kubectl apply -f hpa-rps.yaml
kubectl -n monitoring port-forward svc/prometheus-server 9090:80   # Prometheus UI
```

Прогоны шли без веб-интерфейса Locust, с теми же параметрами, что задаются в нём. Первая попытка части 1 — `locust --headless -u 1000 -r 20 -t 6m`, вторая попытка и часть 2 — `locust --headless -u 1000 -r 2 -t 9m`, то есть до 1000 пользователей, по 2 новых в секунду, 9 минут. Пока шла нагрузка, раз в 10 секунд в лог записывались состояние HPA, Deployment, `kubectl top pods` и список подов со счётчиком перезапусков. Как только счётчик перезапусков рос, сразу снимались `kubectl describe pod` и `kubectl get events`.

Прогоны сделаны 17 ноября 2026 года, часть 2 — сразу после полуночи, 18 ноября. Время везде московское.

Перед каждым прогоном Deployment перезапускался (`kubectl rollout restart`), чтобы прогон начинался с нового пода, поэтому в логах разных прогонов разные имена подов. HPA перед каждым прогоном удалялся и создавался заново из нужного манифеста, поэтому в каждом describe HPA только события своего прогона.

## Часть 1. Масштабирование по памяти

Лимит памяти — 30Mi. Requests выставлены равными лимиту: HPA считает утилизацию в процентах от requests, а не от limits. Цель — 80%, то есть около 24Mi на под.

### Первая попытка

metrics-server в аддоне Minikube снимает метрики раз в 60 секунд (`--metric-resolution=60s`), нагрузка набирается быстро: по 20 пользователей в секунду, все 1000 запущены за 50 секунд. Файлы: [лог](results/part1-first-attempt-watch.log), [describe HPA](results/part1-first-attempt-hpa-describe.txt), [describe подов](results/part1-pod-oom-describe.txt), [события](results/part1-first-attempt-events.txt), [итоги Locust](results/part1-first-attempt-locust-summary.txt), [история Locust](results/part1-first-attempt-locust-history.csv).

| Время (МСК) | Что произошло |
| :- | :- |
| 23:25:03 | старт нагрузки, 1 реплика, память 27% |
| 23:25:40 | первое обновление метрик после старта: 53% (16Mi) |
| 23:25:57 | под упёрся в лимит и был убит: `Last State: Terminated, Reason: OOMKilled, Exit Code: 137`. Следующего обновления метрик он не дождался |
| 23:26:38 | HPA увидел 95% и добавил вторую реплику: `New size: 2; reason: memory resource utilization (percentage of request) above target` |
| 23:26:51 | вторая реплика тоже OOMKilled, через 13 секунд после создания пода |
| 23:27:40 – 23:33:30 | HPA показывает `<unknown>`: поды по очереди перезапускаются, метрик по ним нет, третья реплика не добавляется |
| 23:31:03 | конец нагрузки; к этому моменту 12 OOMKilled, по 6 на каждый под |
| 23:32:10 | оба пода в `CrashLoopBackOff` |
| 23:33:50 | без нагрузки оба пода снова `Running` |

За прогон — 110 954 запроса, 54 462 ошибки (49,09%), медиана ответа — 3 мс. Первые ошибки — в 23:25:57, в момент первого OOMKilled.

Под упёрся в лимит через 54 секунды после старта, раньше, чем metrics-server второй раз обновил данные. HPA увидел превышение цели только в 23:26:38, когда под был убит уже трижды. Вторая реплика попала под тот же поток и тоже упала. Пока поды перезапускаются, метрик по ним нет, и HPA больше ничего не делает.

Поэтому сделаны две вещи: metrics-server снимает метрики раз в 15 секунд (`--metric-resolution=15s`), а нагрузка набирается плавно, по 2 пользователя в секунду.

### Вторая попытка

Файлы: [лог](results/part1-hpa-memory-watch.log), [describe HPA](results/part1-hpa-memory-describe.txt), [describe подов](results/part1-pod-oom-describe.txt), [события](results/part1-events.txt), [итоги Locust](results/part1-locust-summary.txt), [история Locust](results/part1-locust-history.csv).

| Время (МСК) | Что произошло |
| :- | :- |
| 23:45:43 | старт нагрузки, 1 реплика, память 28% |
| 23:50:10 | память 82%: выше цели, но в пределах допуска, реплика не добавляется |
| 23:50:30 | 86% — всё ещё в пределах допуска |
| 23:50:54 | HPA добавил вторую реплику (в логе в 23:51:00 — 89%): `New size: 2; reason: memory resource utilization (percentage of request) above target` |
| 23:51:30 | первый под — 29Mi из 30Mi, новый — 10Mi |
| 23:52:17 | первый под OOMKilled |
| 23:53:58 | второй под OOMKilled |
| 23:54:20, 23:54:39 | оба пода OOMKilled ещё раз |
| 23:54:43 | конец нагрузки, реплик по-прежнему 2 |

С 23:51:30, когда HPA стал считать среднюю по двум подам, и до конца нагрузки она держалась от 41% до 80%, не выше цели, поэтому третья реплика не добавлялась, хотя поды по очереди упирались в лимит.

За прогон — 97 175 запросов, 385 ошибок (0,40%), все в моменты OOMKilled: в истории Locust счётчик ошибок растёт только в 23:52:16–23:52:17, 23:53:59–23:54:00, 23:54:20–23:54:21 и 23:54:40. Медиана ответа — 4 мс.

Выводы:
- HPA реагирует не сразу на 80%: срабатывает с допуском 10%, то есть примерно с 88%. В прогоне при 82% и 86% реплика не добавилась, при 89% — добавилась. При лимите 30Mi между этим порогом и лимитом остаётся около 3,6Mi.
- Добавленная реплика не разгружает старый под. Похоже, дело в keep-alive: пользователи Locust держат соединения открытыми, и новая реплика получает только часть новых пользователей (в части 2 это видно по RPS подов разного возраста), а память старого пода продолжает расти. Первый под упал через 83 секунды после добавления реплики. HPA смотрит на среднюю память по подам, а в лимит упирается каждый под отдельно.
- Для этого приложения память — плохой сигнал: реплика добавляется почти тогда же, когда под упирается в лимит, а после нагрузки память почти не снижается. В части 2 через 5 минут после остановки нагрузки средняя память подов — те же 50%, что и под нагрузкой ([лог](results/part2-hpa-rps-watch.log), 00:11:25 и 00:16:35). HPA по памяти оставил бы 5 реплик из 7 (7 × 50 / 80 с округлением вверх), а HPA по запросам вернулся к одной. Нагрузку лучше отражает число запросов, отсюда часть 2.

## Часть 2. Масштабирование по запросам в секунду

- Prometheus находит поды по аннотациям `prometheus.io/*` в Deployment и раз в 15 секунд забирает `/metrics`. Скриншот targets: [part2-prometheus-targets.png](results/part2-prometheus-targets.png) (снят после прогона, когда осталась одна реплика; что под нагрузкой Prometheus находил все семь подов, видно по [графику числа подов](results/part2-prometheus-pod-count.png)).
- prometheus-adapter превращает счётчик `http_requests_total` в метрику `http_requests_per_second` для каждого пода (`rate` за минуту) и публикует её в Custom Metrics API ([ответ API под нагрузкой](results/part2-custom-metrics-api.json.txt), 00:10:57).
- HPA ([hpa-rps.yaml](hpa-rps.yaml)) держит в среднем 50 запросов в секунду на под. Цель взята с запасом от части 1: там один под без ошибок обрабатывал около 176 запросов в секунду ([история Locust](results/part1-locust-history.csv), 23:50:10).

Прогон ([лог](results/part2-hpa-rps-watch.log), [describe HPA](results/part2-hpa-rps-describe.txt)). В последнем столбце — среднее RPS на под, при котором HPA добавил реплику; оно посчитано ещё по прежнему числу подов.

| Время (МСК) | Реплик | RPS на под, при котором HPA добавил реплику |
| :- | :-: | :-: |
| 00:02:28 | 1 | старт нагрузки |
| 00:04:28 | 2 | 59,5 |
| 00:05:58 | 3 | 59,4 |
| 00:07:13 | 4 | 55,8 |
| 00:08:42 | 5 | 57,5 |
| 00:09:57 | 6 | 55,9 |
| 00:11:27 | 7 | 55,3 |
| 00:11:28 | 7 | нагрузка остановлена |
| 00:12:45 | 7 | 0 |
| 00:16:40 → 00:17:10 | 7 → 4 → 2 → 1 | 0, реплики убраны примерно через 5 минут после остановки нагрузки (стандартное окно стабилизации при уменьшении) |

За прогон — 97 043 запроса без ошибок, медиана ответа — 4 мс ([итоги Locust](results/part2-locust-summary.txt), [история Locust](results/part2-locust-history.csv)). Перезапусков подов не было.

Графики Prometheus за этот прогон (время на графиках в UTC, на 3 часа меньше МСК):
- [число подов](results/part2-prometheus-pod-count.png): `count(count by (pod) (http_requests_total{namespace="default"}))`;
- [запросы в секунду по подам](results/part2-prometheus-rps-by-pod.png): `sum by (pod) (rate(http_requests_total[1m]))`.

Нагрузка по подам неравномерная. В [ответе Custom Metrics API](results/part2-custom-metrics-api.json.txt) в 00:10:57 у шести подов 150,9, 74,2, 47,3, 29,7, 14,6 и 2,9 запроса в секунду, в среднем 53,3. Чем раньше под появился, тем больше у него запросов (возраст подов — в [логе](results/part2-hpa-rps-watch.log), 00:10:55). kube-proxy распределяет соединения, а не запросы, а Locust держит соединения открытыми (keep-alive). Новые поды получают только соединения новых пользователей. HPA добавлял реплику, когда среднее доходило до 55–60 запросов в секунду на под, а после первого добавления среднее по HPA было от 40 до 69. Самый нагруженный под при этом получал 150,9 запроса в секунду и занимал до 25Mi из 30Mi — 83% лимита ([лог](results/part2-hpa-rps-watch.log), 00:09:35). Значит, при таком перекосе HPA по среднему RPS не защищает отдельный перегруженный под. Нужна балансировка по запросам, а не по соединениям (L7: NGINX, service mesh), или ограничение запросов на под.

## Замечания по стенду

- Итоги прогонов взяты из сводки Locust по завершении. История Locust (CSV) пишется раз в секунду без последней секунды, поэтому счётчики в её последней строке чуть меньше.
- Между удалением и созданием HPA выдерживалась пауза больше 5 минут. Без неё новый HPA сразу ставил 2 реплики с пустой причиной (`New size: 2; reason:` в [событиях](results/part1-events.txt)); после паузы такого не было.
- Mac на Apple Silicon, а образ `scaletestapp` собран только под amd64. containerd на arm64-ноде такой образ не принимает, поэтому на стенде образ перепакован с пометкой arm64 и загружен в Minikube заранее; бинарник внутри тот же и выполняется через Rosetta. В манифесте остался исходный образ `ghcr.io/yandex-practicum/scaletestapp:latest`, добавлен `imagePullPolicy: IfNotPresent`. На amd64-кластере ничего этого не нужно.

  ```bash
  echo 'FROM --platform=linux/amd64 ghcr.io/yandex-practicum/scaletestapp:latest' \
    | docker build --platform linux/arm64 -t scaletestapp-arm64wrap -
  docker save scaletestapp-arm64wrap -o /tmp/app.tar && docker cp /tmp/app.tar novamarket:/var/app.tar
  docker exec novamarket sh -c 'ctr -n k8s.io images import /var/app.tar && \
    ctr -n k8s.io images tag docker.io/library/scaletestapp-arm64wrap:latest ghcr.io/yandex-practicum/scaletestapp:latest'
  ```
