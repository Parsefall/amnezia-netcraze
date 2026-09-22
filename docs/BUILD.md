# Сборка и выпуск

**Русский** | [English](BUILD.en.md)

Нужны Git, Go 1.25+ (готовый движок собран 1.25.14), Python 3.10+. Сборка закреплена на commit и проверяет точный diff патча S4.

Linux: `bash build/build.sh`.

Windows:

```powershell
powershell -File build/build-userspace.ps1 -Go C:\Go\bin\go.exe
```

Docker из корня: `docker build -f build/Dockerfile -t awg3-builder .`, затем `docker run --rm -v "$PWD/prebuilt/kn-1012:/out" awg3-builder`. Этот путь не испытан при подготовке первого релиза.

Сборка обновляет только amneziawg-go. CLI awg 3.1.20260812 унаследован. Официальный исходный snapshot tools приложен к релизу вместе с build-файлами. Побитовая воспроизводимость CLI не заявляется. Смотрите NOTICE и BUILD-INFO.

После пересборки движка обновите сведения о компиляторе и SHA256 в BUILD-INFO.json: упаковщик отвергает несовпадающий хеш вместо публикации устаревшей метаинформации.

## Проверки — Linux / Git Bash

```sh
sh tests/test_split_config.sh
sh tests/test_parser_edge_cases.sh
sh tests/test_service.sh
python build/package.py
```

Для Go-регрессии скопируйте tests/go_profile_smoke_test.go в device закреплённых исходников как router_smoke_test.go, выполните `go test ./device ./conn ./replay ./tai64n` на хостовой архитектуре. Для повторов: `go test ./device -run 'TestRouter|TestAWGDevicePing' -count=10`. Перед сборкой релизного движка удалите только добавленный тест: скрипт требует точного diff одного патча.

CI запускает shell-тесты и упаковку на Ubuntu; NDMS он не эмулирует.

## Пакет

`python build/package.py` создаёт outputs/awg3-netcraze-arm64-userspace.tar.gz, внешний .sha256 и внутренний SHA256SUMS. Только allowlist: без ключей, личных профилей, логов и .ko.

Первый релиз публикуется из чистого snapshot без истории рабочего каталога. Проверяйте staged diff и архив перед каждым выпуском. Хеш из того же релиза проверяет целостность, но не является независимой цифровой подписью.
