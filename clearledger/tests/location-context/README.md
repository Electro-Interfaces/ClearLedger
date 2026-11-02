# Изоляция locationService при смене компании — M12/M17

База: `5ce5779b20151a8d04de7d3a1681d1862a80d9dd`, ветка
`fix/location-company-context-20261029`. Локальная правка, без выпуска и обращения
к рабочим API, БД, ВМ или credentials.

`CompanyContext` выбирает компанию сервисов до изменения React state. Один общий
переход обслуживает первый выбор, ручную смену, изменение доступного списка и
смену пользователя. Смена пользователя с той же компанией тоже сбрасывает кеши.
`loadLocations` больше не выбирает компанию сам: запрос другой компании при
действующей границе отклоняется до HTTP.

`locationService` фиксирует компанию и поколение до await. Смена компании либо
`resetCache` инвалидируют поколение, в том числе при возврате в ту же компанию.
Поздние успех/ошибка/пустой ответ отклоняются `AbortError`, без localStorage
fallback и mirror POST; await-продолжение не получает успешный результат.
Проверка есть также перед обновлением зеркала после `setOperationalStatus`.
Ключи хранилища после await и `company_id` зеркального POST используют захваченную
компанию. `useLocations` передаёт signal React Query в существующий
`apiClient.get(path, params, { signal })`; старые вызовы GET совместимы.

`DocFilters.ref?: string` отражает существующий backend-фильтр предмета/цели связи.
`ContractDocumentsBlock` передаёт его без `as never`; URL, сериализация, opaque ID
и поведение документооборота сохранены.

Запуск из `clearledger`:

```bash
node --test --experimental-strip-types src/lib/locationService.test.ts
npm run test:unit
npm run typecheck
node node_modules/typescript/bin/tsc --noEmit -p tests/location-context/tsconfig.json
git diff --check
```

Целевые тесты загружают настоящие service/apiClient-модули через имеющийся Vite,
с `configFile: false`, `envFile: false`, без HTTP/HMR-сервера. Каждый fetch
перехвачен; браузерные хранилища синтетические. В проверке hook заменяются только
вызовы `useCompany`/`useQuery`; настоящий `useLocations` создаёт options для
настоящего `QueryObserver`. Это проверяет отмену `qc.clear()` на пути hook →
service → transport, включая поздний ответ транспорта, проигнорировавшего abort.

Покрыты A→B, reset→A и reset без нового выбора, устаревший повторный вызов A,
late error, пустой stale backend без mirror, актуальная гидрация, отмена до и
после отправки, late/current status mutation и await→mutation, сериализация ref,
offline/demo и сохранение существующей миграции актуального локального списка.
Type fixture принимает строковый ref и через `@ts-expect-error` отвергает число.

Результаты 29.10.2026: целевые тесты **17/17 PASS**, полный `test:unit`
**273/273 PASS**, `npm run typecheck` **PASS**, typed-ref fixture **PASS**,
`git diff --check` **PASS**. Проверены исходники именно этой ветки, не соседнего
дерева. Зависимости взяты из дерева `rh-acct-status-release-20261029` на той же
базе с совпадающим SHA256 `package-lock.json`
`33e8580295715406eab6ca35a84a4d2b5da7b5ea4c4e0bef0822d02cd9e41d92`;
локальная `.tmp` для tsc изолирована. Все 530 установленных package entries
совпали с lock этой ветки по версии и integrity. Package/lock/dependency config
не менялись.

Точечный ESLint: **5 ошибок / 2 предупреждения** в `CompanyContext`, те же правила
и участки, что у исходного `5ce5779b` (проверено через `git show` и ESLint stdin).
Это прежние set-state-in-effect, preserve-manual-memoization, exhaustive-deps и
only-export-components. Остальные изменённые исходники и тесты проходят ESLint.

Ограничения: браузерный сценарий CompanyProvider и рабочее окружение не проверялись.
Другие потребители `loadLocations` могут пока не передавать signal, но защищены
проверкой поколения. Уже отправленную серверную команду эта правка не откатывает;
она запрещает локальные эффекты и следующие команды устаревшего продолжения.
Существующие online fallback и миграция local→backend для **актуального** запроса
сохранены; это не реализация всех изменений M12/M17. В demoApi по-прежнему нет
`/api/locations`, и demo-чтение использует прежний локальный fallback.
