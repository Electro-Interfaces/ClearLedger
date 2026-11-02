# Актуальные протоколы Core на cdd68e7b, M01/M09

**Все44 исторические специальные операции сопоставлены с текущими source registrations; общий comparison —75source-file facts, из них55same/20drift. Следующий узкий codepatch proposal: только cache header `xlsx_response` для7 существующих callers.** Production0/runtime0; реализации и нового runtime registry здесь нет. M01/M09 и общая программа20M+11 остаются active.

Работа в своей `agent/api-protocol-current-20261031` от accepted P11 `cdd68e7b07461b2306a0b0ecdd89da9edc9334c7` после clean/fetch/HEAD=origin. Разрешены только эти2NEWreports и ignored source proofs. Старые passports, CURRENT/COMPOSED, app/src/tests/tools/schema/deps и соседние worktree сохранены. Scope ROOT: `msg_0d2996eec015`; отдельный pre-read XLSX: `msg_9341f295a37a`.

## Точные знаменатели и происхождение

| Срез / наблюдение | Число и предел |
|---|---|
| Historical special catalogue |44operations /40endpoint functions |
| Historical integration comparators |31operations, не дополнительные special protocols |
| Combined source-file facts |75 =44+31; не75 специальных API |
| Current cdd whole-file comparison |55same /20drift |
| Function AST,75fact rows |71same /4drift; console function повторяется для5methods; не71same unique functions |
| Уникальные endpoint functions |71всего:67ASTsame /4drift; не semantic/runtime equivalence |
| Уникальные reviewed source files |62всего:45same /17drift; sourceHashes включает helpers/frontend/deps, не62operations |
| independently recomputed56931683 comparison |58same /17drift, исторический срез |
| Historical actual e1cb1a53 |1703operations /12curated /1WS, immutable input |
| Historical actual56931683 |1706operations /15curated /1WS, COMPOSED receipt |
| Current cdd actual total |**unknown**, app не импортировался |
| Current all-app AST |494Python modules;1702route-decorator candidates, не actual denominator |
| Current special discovery |106function candidates:40historical endpoint candidates +66newly catalogued/internal;29multipart functions;0literal SSE candidates |

44/40 и75 keys проверены против полного immutable runtime input e1cb SHA `f056e74b77564f8b1a9f650bf2dc87dbc24ad1bd558d6df967ef5fab86fa2af8`. Historical MD/JSON прочитаны полностью; их bytes/hashes не переписаны. Current source matching использует decorators, конкретный APIRouter prefix, source `main.include_router` и для product child `operation→PolicyRouter.operation(methods=GET)→include_router→mount`. Flags/readiness/source registration не считаются фактической доступностью. Все44 имеют current literal chain, но текущие order/generated IDs/actual startup unknown.

Разные знаменатели не суммируются:55/20 —75operation-source file facts;71/4 — AST сравнения тех же75строк;67/4 —71уникальнаяendpoint function;45/17 —62уникальных reviewed source files. Historical58/17 сохранён без переименования.

Stable identity — logical authority + protocol + method + path. Для44 authority — Core `app.main.app`, кроме S09 с отдельным product child `/api/v1`; физический gateway/authority unknown. Старые ordinal/order/generated ID сохранены в JSON только как provenance; совпавший suffix ID не является контрактом и не заменяет регистрацию.

Полные MD/JSON CURRENT и COMPOSED прочитаны из immutable ROOT Git pin `0a206bac567697abeae8a5d7eb9e8ecd8ea3d30e:docs/api/…` и проверены по SHA. Они по-прежнему описывают Core264ad50b/56931683, а не cdd. CURRENT JSON SHA `ff144d91c4c9f453736017cb1623ee43dd17f52fac2d54c20ddd86347bce88cf`; COMPOSED JSON SHA `ca668c80019f554f81420d9577bd2704858f170f0569b32055cfdde0e70d7054`. Их2491surfaces,640source consumer candidates и5267TS AST records не переносятся в текущий actual. Support/Auditor/Deploy READONLY, новый whole-app export не выполнялся.

## Source coverage и воспроизведение

`scan.py` stdlib-only получает immutable Git blobs выбранного cdd app/src/tests/schema/tools; никаких application imports. Source manifest `98fd4c869efed9d1170031b0bcce14a1b191acfc3ca870019250d58893faf0ed`; app Git tree `f7026843542d73384a9e6b603570c468ab4e4fee`. В selection2143current files: app504,src1220,tests386,schema24,tools9. С historical/mid blobs scanner2203reads /43,919,946bytes /19.43s. Четыре broad-registry inputs добавляют26,953,233bytes, суммарная входная selection<100MiB. Caps90s/scanner,10kfiles,100MiBsource,8MiBnewJSON. Большие historical registry JSON≈13.46MB — pinned read-only inputs, не новые outputs.

```sh
/home/mag/.local/bin/python3.13 -I -S -B .artifacts/core-protocol-current-20261031/scan.py
/home/mag/.local/bin/python3.13 -I -S -B .artifacts/core-protocol-current-20261031/enrich.py
```

Это bounded source discovery, не replacement existing global registry pipeline. Import aliases/nested functions, Response-as-FileResponse, custom operation factory, module helpers и literal MIME/WS/multipart signatures учтены. 106 — functions/helpers, не106routes. Arbitrary assignment aliases/getattr/exec/runtime loaders/unknown factories/gateway остаются unknown. Known `books_links.py:144` escape SyntaxWarning сохранён; source AST parsed. Worker не выполнял app/main, collection/tests/SQL/Node/серверы/jobs/installer/containers/network к приложениям. Только официальные standards pages читались по HTTPS.

## Все44 текущие специальные операции

Полный JSON для **каждой** строки содержит current file+SHA/lines/function hash, current decorator/mount, admission predicates/source helpers, company/object selectors, content/status/errors/headers/filename, privacy/cache, renew/revoke/limits/consumer candidates и scoped changes/unknowns. Подписи профилей ниже раскрывают повторяющиеся правила; dependency/tag/URL prefix сами по себе не ACL proof.

| ID | Method/path | Current technical owner / line | Profile | Source comparison |
|---|---|---|---|---|
| S01 | `WEBSOCKET /api/chat/ws` | `chat_router.chat_ws`:3234 | W | file drift; function same |
| S02 | `DELETE /api/store/station/{station_id}/console/{path:path}` | `station_console_router.station_console`:239 | C | file=function same |
| S03 | `GET /api/store/station/{station_id}/console/{path:path}` | `station_console_router.station_console`:239 | C | file=function same |
| S04 | `HEAD /api/store/station/{station_id}/console/{path:path}` | `station_console_router.station_console`:239 | C | file=function same |
| S05 | `POST /api/store/station/{station_id}/console/{path:path}` | `station_console_router.station_console`:239 | C | file=function same |
| S06 | `PUT /api/store/station/{station_id}/console/{path:path}` | `station_console_router.station_console`:239 | C | file=function same |
| S07 | `POST /api/store/station/{station_id}/session` | `station_console_router.station_console_session`:200 | C0 | file=function same |
| S08 | `GET /api/files/{file_id}` | `intake_router.download_file`:112 | F | file=function same |
| S09 | `GET /api/v1/documents/{docId}/versions/{versionId}/content` | `app.create_product_api.<locals>.document_content`:235 | P | file drift; function same |
| S10 | `GET /api/store/documents/{record_id}/files/{file_row_id}/download` | `store_documents_router.document_file_download`:1715 | S | file=function same |
| S11 | `GET /api/store/documents/{record_id}/print` | `store_documents_router.document_print_form`:1491 | S | file=function same |
| S12 | `GET /api/sites/{site_id}/docs/{doc_id}/file` | `sites_router.download_site_doc`:1019 | M | file drift; function same |
| S13 | `GET /api/sites/{site_id}/tech-connection/shared-documents/{doc_id}/file` | `sites_router.download_tp_shared_document`:1204 | M | file drift; function same |
| S14 | `GET /api/sites/{site_id}/tech-connection/application` | `sites_router.tech_connection_application`:1224 | M | file drift; function same |
| S15 | `GET /api/partner-space/attachments/{attachment_id}` | `space_bridge_router.partner_attachment`:600 | M | file=function same |
| S16 | `GET /api/mail/attachment` | `mail_router.attachment`:276 | MC | file=function same |
| S17 | `GET /api/tasks/attachments/{attachment_id}` | `tasks_router.download_attachment`:2156 | T | file drift; function same |
| S18 | `GET /api/work/calendar/{event_id}/papers/{paper_id}/file` | `work_router.paper_file`:2441 | E | file drift; function same |
| S19 | `GET /api/doc-share/{token}/file/{version_id}` | `doc_share_router.download`:187 | L | file=function same |
| S20 | `GET /api/work/calendar/feed/{token}.ics` | `work_router.calendar_feed`:1413 | K | file+function drift |
| S21 | `GET /api/work/calendar/{event_id}/ics` | `work_router.calendar_ics`:1498 | EP | file+function drift |
| S22 | `GET /api/invite/{token}/ics` | `invite_router.invite_ics`:233 | I | file+function drift |
| S23 | `GET /api/export/excel` | `export_router.export_excel`:136 | A | file=function same |
| S24 | `GET /api/export/csv` | `export_router.export_csv`:192 | A | file=function same |
| S25 | `GET /api/store/doc-files/archive` | `store_router.store_doc_files_archive`:3170 | SN | file=function same |
| S26 | `GET /api/store/reports/{kind}` | `store_router.store_network_report`:2239 | SC | file=function same |
| S27 | `GET /api/store/reports/goods-report/print` | `store_router.store_goods_report_print`:2213 | SC | file=function same |
| S28 | `GET /api/sites/export/{report}` | `sites_router.export_report`:523 | M | file drift; function same |
| S29 | `GET /api/sites/{site_id}/report.xlsx` | `sites_router.project_report_xlsx`:774 | M | file drift; function same |
| S30 | `GET /api/corporate/billing-export` | `corporate_router.corporate_billing_export`:119 | MS | file=function same |
| S31 | `GET /api/charge-sessions/export` | `charge_sessions_router.export_sessions`:658 | MS | file=function same |
| S32 | `GET /api/charge-sessions/export/pivot` | `charge_sessions_router.export_sessions_pivot`:740 | MS | file=function same |
| S33 | `GET /api/charge-sessions/export/monthly-matrix` | `charge_sessions_router.export_monthly_matrix`:772 | MS | file=function same |
| S34 | `GET /api/reconciliation/export` | `reconciliation_router.export_reconciliation_act`:91 | M | file=function same |
| S35 | `GET /api/docs/reports/export` | `docs_router.export_report`:1905 | D | file drift; function same |
| S36 | `GET /api/docs/export` | `docs_router.export_docs`:2088 | DL | file drift; function same |
| S37 | `GET /api/docs/{doc_id}/print` | `docs_router.print_doc`:3427 | DP | file drift; function same |
| S38 | `GET /api/docs/{doc_id}/export/download` | `docs_router.download_package`:4574 | DX | file drift; function same |
| S39 | `GET /api/pulse/export` | `pulse_router.pulse_export`:596 | MP | file drift; function same |
| S40 | `GET /api/edge/alerts` | `edge_router.alerts`:1528 | AK | file=function same |
| S41 | `GET /api/developer/docs/assets/{name}` | `docs_portal_router.asset`:118 | G | file=function same |
| S42 | `GET /api/developer/docs/ui` | `docs_portal_router.ui`:125 | G | file=function same |
| S43 | `GET /api/developer/docs/oauth2-redirect` | `docs_portal_router.oauth_redirect`:151 | G | file=function same |
| S44 | `GET /api/oauth2/authorize` | `partner_oauth_router.authorize`:104 | O | file=function same |

## Текущие admission/transport profiles

| Код | Admission | Tenant/object boundary | Privacy, renewal, limits |
|---|---|---|---|
| W | query JWT decode(exp), UUID sub, live User and session_valid before accept; not HTTP get_current_user; denied close1008 before accept is not guaranteed browser frame | initial default user.company_id; fresh member IDs OR retained default company for company subscribe; chat participant owner for chat UUID | exact chat query logging fixed for known uvicorn.error/access formats; arbitrary debug/gateway unknown; HTTP refresh does not update accepted socket; manager metadata only user_id/company_id; no exp/tv recheck for ordinary delivery/ping; no per-frame/connection/channel/replay cap in selected handler; deployment WS limits unknown |
| C | console-cookie JWT typ/station/expiry→sub/company→fresh UserCompany.business_grants→station-admin | station_id/path plus cookie company; selected station grant checked before fixed-Hub request; not general product permission | server integration key outbound only; input Authorization/Cookie not forwarded; response header filtering is partial; no broad privacy certification; 60min idle cookie renewed after upstream response/grant; no token_version/session_valid link; absolute lifetime unknown; buffered request.body + HTTPX.content/text, timeout130s; no local body cap in handler; no WS upgrade/SSE bridge |
| C0 | HTTP JWT→scope_company_id→current business_grants→station-administrator; 204 sets bound Secure HttpOnly SameSite=Lax cookie | selected company + station_id; cookie path exact console prefix | cookie admission, not product OAuth; no-store not explicitly set in constructor; cookie max-age3600; subsequent C check different from user JWT refresh/revoke; station integer path/framework validation; cookie expiry3600s |
| F | HTTP JWT and get_owned(SourceFile); independent store/task/docs/conf gates, then live chat copy with participant/history; not membership alone | file UUID→SourceFile.company_id; accessible live chat source copy; history cutoff nullable | private,no-store explicit; native FileResponse filename/stored MIME; byte range/dependency behavior not executed; new HTTP request checks current User/session/membership and resource gates; browser-stored copies beyond server authority; file UUID400/404; no local download byte cap; dependency ranges unknown |
| P | access.resolve→verified principal/company/resource grants→BoundPolicyRoute documents:read AND files:download→Query.detail→file ACL | doc/version/source exact company; shared chat/conf/store/task file denied; no filename-only authority | opaque octet-stream; attachment filename*; no-store/nosniff; no generic Range/ETag promise; verified current token/grant per request, flags defaultOFF; docs cookie is not business grant; 64KiB generator chunks; confined no-follow regular file; total file cap not declared; no current wire runtime |
| S | router module gate plus resolve_document_access current network/station grants→projection | record/projection station+company; file row current/non-tombstone record/doc_ref and SourceFile.company_id | HTML or stored-MIME FileResponse; no explicit no-store on selected success; main conditional_get applies JSON only; current grants per HTTP request; no-stale-link guarantee depends on fresh guards; 404; print409 no form; no local response byte cap |
| M | HTTP JWT and assert_company_member; owning site/organization/resource predicates where explicit; report-level membership is not object-scope proof | company plus site/doc/report specific selectors; builder row scope unverified where not traced | per-route HTML/binary headers differ; no universal no-store supplied by JSON-only middleware; HTTP session/current membership per request; resource-specific revoke must be independently checked; source Query bounds and report allowlists; generic byte/global body limits unknown |
| MC | HTTP JWT→_mail_scope→assert_company_product(connect) | attachment_id AND company SQL; company mail not personal mailbox ACL | stored MIME fallback; attachment filename*; empty404; no explicit no-store success; current HTTP token/product grant per request; DB content buffered; no explicit byte cap in attachment handler |
| MS | HTTP JWT→assert_company_product(sales); does not prove every station/object row filter | company/date/client/user type/stations/regions; current actual row-level matrix not executed | xlsx_response MIME/disposition only, no explicit no-store; export audit can write and schedule guard; current HTTP token/product grant per request; underlying saved copies not revocable; route Query defaults/ceilings from current signature; workbook fully buffered; declared total byte cap absent |
| T | HTTP JWT→native _assert_work→task_access.assert_work(docs fallback plan/current product_gate); task view + authorize_task_file_download | attachment.task_id→Task.company_id + current visibility; SourceFile.company_id + disk exists | private,no-store; stored MIME fallback; native FileResponse filename; live token/member/product/task view on each request; preserve private/personal/admin/oversight differences; UUID400 / attachment/task/file404; no explicit download byte cap |
| E | HTTP JWT→work _assert_work docs/plan→_event_of_member→event/paper/file relation; member visibility is not task ACL | company/event and paper.event_id/file_id; SourceFile.company_id not explicitly checked in paper_file | private,no-store; stored MIME fallback; association integrity is separate unresolved question; fresh HTTP admission/event member; token revocation only on future HTTP requests; UUID400/foreign/event/paper404; no explicit response byte cap |
| EP | HTTP JWT→work _assert_work→_event_participant | company/event/organizer-or-attendee; current one-event representation | text/calendar; attachment meeting.ics; no explicit no-store in route; persisted SEQUENCE now calendar_protocol.version; HTTP token/member/product/participant rechecked per GET; 400/404; one finite event, byte cap not declared |
| L | document capability hash/legacy token, expiry/revoked/snapshots→not-strict document→allowlisted version | version snapshot AND doc/version chain/archive not purged→SourceFile; no standalone company/JWT grant | no-store/no-referrer/noindex; uniform404; SourceFile association trusted beyond doc chain; capability revoke/expiry per GET; not JWT refresh; snapshot purpose preserved; version snapshot allowlist; file body cap not declared |
| K | anonymous bearer capability User.calendar_feed_token; min length20; no JWT/product/membership gate in feed read | organizer OR attendee through native wrapper→calendar_queries.my_events_clause; date window; no company-wide selector | text/calendar inline trek.ics no-store; token in path must be treated as credential by future privacy review; token rotation invalidates lookup; no expiry/revoked field read; current membership revoke not equivalent to token rotation; ±365days starts_at; no row LIMIT; finite generated file not SSE |
| I | anonymous guest capability hash + revoked_atNULL; expiry checked only if non-null; event exists | guest.event_id→single CalendarEvent; organizer metadata; not user/company membership grant | text/calendar attachment meeting.ics; no explicit no-store in route; current persisted SEQUENCE; guest revoke/expiry per GET; null expiry behavior preserved; no JWT refresh; one event; missing/expired/revoked404; no explicit bytes cap |
| A | HTTP JWT→_export_company_id→company admin/current superadmin | required company/selected fallback validated by require_company_admin; _fetch_entries company WHERE | XLSX or CSV BOM buffered in StreamingResponse; no explicit no-store; audit export, not pure read; current HTTP token/admin grant per GET; max100000entries; no memory/bytes cap in helper; Range unknown |
| SN | HTTP JWT→store module→scope_company_id→resolve_document_access network-only | company/live StoreDocFile; period/station selectors; row/file chain | ZIP StreamingResponse in-memory, X-Archive-Name/X-Files-Count; no global file ACL substitute; fresh current grants each request; 413 if more than2000 rows OR stored size sum>1500000000; ZIP fully buffered, actual compressed size and global memory ceiling not proven |
| SC | HTTP JWT→router store module→scope_company_id; selected-company fallback is not per-row station proof | company/report kind/date/stations→builder; source alias FileResponse is actually fastapi.Response | HTML print or buffered CSV/XLSX; no explicit no-store on selected branch; current HTTP module grant; station-scoped builder coverage unknown; kind allowlist/404; body fully buffered; row/byte cap per builder unknown |
| D | HTTP JWT→assert_company_product(docs), report delegate including current report-specific checks | company/report/date; report-specific supervisor scope; no universal docs export grant | XLSX helper no-store gap; normal failure uses current HTTP detail; HTTP token/member/product/report gates per GET; report allowlist/bounds from source signatures; workbook buffered |
| DL | HTTP JWT→list_docs pagination with current_user and original filters; no independent unconditional export SQL | company + registry filter and visibility of list_docs; preserve caller policy | CSV BOM native Response or XLSX helper; no explicit no-store; export audit permitted; HTTP token/member/doc grant per GET; pagination loop per source, total export rows/bytes not globally capped by formatter |
| DP | HTTP JWT→docs product→_doc_or_404→_assert_doc_permission(print)→doc_access._can_doc | company/document/current print permission; not membership alone | generated HTML private,no-store; no original source passthrough; current HTTP token and print permission per GET; 403/404; finite render, size cap not declared |
| DX | HTTP JWT→docs product→export AND download checks, row lock/populate_existing then both checks repeated | current doc/company/retention-state; package built from allowed current chain | ZIP private,no-store; filename*; audit/commit intentionally preserved; recheck current permission after lock; source says no snapshot authority reuse; 403/404/409 retention; memory/binary cap per package builder unknown |
| MP | HTTP JWT→pulse product; _sees_money gates week money rows; objects adds business.objects; operations has no separate item check in this handler | company→week/object/ops snapshots; owner pulse_day identity imports; company filters do not establish row-scope completeness | CSV BOM; filename pulse-*; no explicit no-store. Historical blanket money description is too broad for operations branch; business intent unknown; current HTTP product grant; revenue permission distinct from operating cost visibility; view regex week|objects|operations; snapshots define dates/population, byte cap absent |
| AK | named current API-key hash/revoke/expiry or legacy company key; station scoped key behavior delegated to auth | key company + supplied station_id→edge_service.alerts; arbitrary station entitlement not attested | JSON default or text/plain no attachment; JSON middleware caching differs from text; key current revocation/expiry per request for named keys; legacy key rotation separate; 401/403; report size bounds not proven |
| G | docs_session→docs_portal.live_session: enabled,cookie digest/expiry/revoke/profile,token/family/live grant/configured publicclient and docs:read | documentation capability; neither docs schema nor cookie grants business records | all success/errors private headers no-store/nosniff/no-referrer through DocsRoute; pinned asset allowlist; CSP self/none; live token/grant checks per request; cookie<=180s and verification-profile rotation; browser polls session10s; asset allowlist4 local files; query config overrides400; live session rawcookie<=256; business Tryout GET-only sandbox |
| O | OAuth throttle+param allowlist+state/nonce/prompt/PKCE consent validation before pending request | validated configuredclient redirect URI; only fixed SPA Location, not arbitrary redirect | 302 no-store; invalid input OAuth JSON no redirect; no business bytes; pending5min; actual code/token/family lifecycle elsewhere, not authorize-only proof; query<=8192/state,nonce<=256; duplicate params validated by parameters |

Status/header summaries вJSON описывают явные handler/helper branches, а не все возможные middleware/server errors. Stored MIME не является гарантированной MIME всех files. SourceFile identity не заменяет task/docs/chat/conf/store permission. Chat participant foreign-denial может писать audit, export helpers могут add AuditEvent/schedule guard; эти операции не объявлены blanket no-write. Explicit commit/flush/rollback/audit calls сохранены в per-function facts; delivery/commit runtime не выполнялся.

## Изменённые тела и сохранённые native hooks

| ID | Function AST drift | Current line |
|---|---|---:|
| S20 | `app.routers.work_router.calendar_feed` | 1413 |
| S21 | `app.routers.work_router.calendar_ics` | 1498 |
| S22 | `app.routers.invite_router.invite_ics` | 233 |
| I27 | `app.routers.conf_router.session_end` | 764 |

Для трёх ICS calendar_protocol.version отвергает non-int/out-of-range persisted revision через RuntimeError; wire500 shape на повреждённой строке не проверялся. Три ICS функции теперь используют `calendar_protocol.version(ev)`; conf.session_end меняет сохранённую organizer revision под прежней транзакцией. Параметры timezone/UID/время/отмена не переопределяются этой ревизией. Accepted revision0002/schema tests — исторические отдельные receipts, а не новый прогон в этой задаче.

Тела многих endpoints остались прежними, но owners изменились: chat `_assert_participant/_history_from`→chat_access; task `_assert_work/_assert_view_task`→task_access; `_my_events_clause`→calendar_queries; Pulse snapshots/day data→pulse_day. Current concrete callbacks company/scope/foreign audit и tasks product gate сохраняются native wrappers; management chat hooks намеренно не удалены. Work `_assert_work` пока отдельный docs→plan helper и не переименован в task_access автоматически. JSON даёт exact owner rebindings+SHA/lines. Participant helper может foreign-audit; helper selector «мои встречи» не является самостоятельной ACL. Native wrappers — совместимость, а не доказательство всех внешних monkeypatch.

## Дополнительное discovery — отдельно от44

29multipart decorated functions найдены по UploadFile/File в signature, включая channels upload, ASUиМ/charge/stations imports, docs/task/calendar/ops/store/recording attachments, OCR/speech. Некоторые существовали на historical pin: «newly catalogued» не означает «newly added API». Каждый кандидат имеет sourceSHA/lines/decorator/response signals/classification вJSON. Multipart request не делает response binary; speech читает≤10MiB+1 и отдаёт JSON, TP shared-document upload≤20MiB/PDF. Ни эти пределы, ни один dependency name не распространяются на все uploads; полный parsing/body limit и ACL не аттестованы.

Дополнительные explicit response callbacks/routes:

| Source/function | Declaration | Статус |
|---|---|---|
| `auth_router.py::gate_check`:572 | router.get('/gate-check', status_code=204) | constructor candidate; source only |
| `docs_portal_router.py::create_session`:74 | router.post('/session') | constructor candidate; source only |
| `docs_portal_router.py::close_session`:94 | router.delete('/session') | constructor candidate; source only |
| `partner_oauth_router.py::discovery`:157 | well_known_router.get('/.well-known/openid-configuration', include_in_schema=False); router.get('/.well-known/openid-configuration') | constructor candidate; source only |
| `partner_oauth_router.py::jwks`:174 | router.get('/jwks') | constructor candidate; source only |
| `partner_oauth_router.py::userinfo`:180 | router.get('/userinfo') | constructor candidate; source only |
| `partner_oauth_router.py::get_request`:216 | consent_router.get('/{request_id}') | constructor candidate; source only |
| `partner_oauth_router.py::approve`:240 | consent_router.post('/{request_id}/approve') | constructor candidate; source only |
| `partner_oauth_router.py::deny`:286 | consent_router.post('/{request_id}/deny') | constructor candidate; source only |
| `security_router.py::trap`:32 | router.api_route('/trap', methods=['GET', 'POST', 'HEAD', 'PUT', 'DELETE', 'OPTIONS', 'PATCH'], include_in_schema=False) | constructor candidate; source only |

JSONResponse также встречается в main rate-limit middleware/exception handlers; эти callbacks не добавляются как endpoint denominator. Внутренние http_cache Response, product files.content/chunks, xlsx_response, chat_ws methods и MIME parser helpers отделены от registrations. Дополнительный pass explicit return delegates (relative imports включены) даёт17candidate edges: product content, current OAuth token/revoke/result_response, admin committed_response, middleware и exception formatters. Depth≤5/edges≤2000/90s, arbitrary callbacks/alias shadowing unknown; это не новые registered operations. S09 factory-delegated bytes установлены через actual source call `files.content`, а не constructor в endpoint. Seven xlsx factory callers перечислены ниже. Нет literal Core SSE в bounded result; `client.stream` во внутренних JSON readers не является browser SSE. Upstream console MIME/другая composition может принести динамический SSE, arbitrary loaders и физический gateway неизвестны.

Outbound URL webhooks теперь имеют shared `services/webhook_delivery.send` owner, fixed signing headers/body, deadline≤10s и response-size bound; `space_events._send` сохраняет отдельную app-target HTTPX ветку. Это исходящая доставка, не второй SSE/proxy/внешний API. Ничего не отправлялось. OCPP/OCPI слова найдены в passport columns/facets/metadata/mappings; существование charging protocol gateway отсюда не следует, внедрение OCPP/OCPI не предлагается.

Consumers: per-operation JSON хранит847prefix occurrences фронтенда, **lexical candidates**, не TypeScript AST/exact method/actual users; повторения между passports сохранены. Исторические5267AST/640matched surfaces остаются привязаны к56931683. Indirect stored file URLs, SDK wrappers, external/mobile consumers и произвольный runtime callgraph unknown.

## Swagger: четыре разных полномочия

1. UI/assets/raw spec gated `DocsRoute→docs_session→docs_portal.live_session`: enabled flags, cookie digest/≤180s expiry/revoke/verification-profile, current token/family/client/live grant/user/docs:read. Privacy headers распространяются и на errors. Asset allowlist4 локальных файлов; query config overrides отклоняются. Main generic docs URLs отключены source config; это не проверка live ingress.
2. `/openapi.server.json` — canonical curated server contract; browser `/openapi.json` — `public_client_openapi` deep-copy projection. Source15product operation decorators не являются current actual15 export. Generated schema/validation в этой задаче не выполнялись.
3. Swagger Authorize — отдельный public Code+PKCE business consent, без client secret; docs cookie не предоставляет бизнес-scopes. portal-init хранит token только в памяти, `persistAuthorization:false`, same-origin config, generation/state/nonce/expiry и logout/revoke.
4. Tryout только при sandboxReady, только GET; live docs session перепроверяется, нужен отдельный business Bearer, business request `credentials:omit`. Disabled sandbox/expired docs/unknown target не считается разрешением. SourceJS review не browser execution.

Исторические actualreports: WS privacy25PASS/2wsprotoSKIP наe6659c6e; этот source fix на месте и старый P-02 не объявлен вновь открытым. BACKEND_UPGRADE_COMPOSED source330: full376 дал375PASS/1schemaFAIL, main8 сначала3PASS/5guardFAIL, затем corrective5PASS; это не single376GREEN/single8GREEN и неcurrentCI. Composed registry actual1706/15 относится56931683. P11 single50PASS — lifecycle каналов, неprotocol conformance44. Эти receipts не складываются в текущий общий runtime сертификат.

## Рекомендуемый основной профиль и специальные границы

Основной профиль для согласованных новых HTTP APIs: versioned HTTP/JSON, explicit typed schema/security/media/status и безопасный Problem contract по выбранному product profile; tenant/resource authorization выполняет owner до bytes. Legacy detail/OAuth errors/HTML/proxy/ICS/binary/WS не переписываются молча в JSON или Problem. JWT query/capability URL, cookie docs, API key и service OAuth — разные authorities. Поддержка content-range/conditional/cancel/replay — отдельные обещания, отсутствующие там, где нет source/actual evidence.

Нормативные основания проверены только по primary official pages; ссылки/версии выбраны явно, conformance всего текущего приложения не заявляется:

| Профиль | Primary specification/version | Применение |
|---|---|---|
| HTTP | [RFC9110 June2022](https://www.rfc-editor.org/rfc/rfc9110.html) | HTTP status/content metadata;405 Allow; URI/log privacy guidance. No universal Problem/JSON requirement |
| PROBLEM | [RFC9457 July2023](https://www.rfc-editor.org/rfc/rfc9457.html#section-3.1.2) | application/problem+json selected profile; status member if generated agrees with actual HTTP status; extensions allowed, not a requirement to convert every legacy error |
| OAS | [OpenAPI3.1.1 2024-10-24 selected compatibility reference, not latest or asserted current emitted version](https://spec.openapis.org/oas/v3.1.1.html#security-requirement-object) | all scopes in one requirement apply together; security-array alternatives differ; schema does not execute ACL |
| CACHE | [RFC9111 June2022](https://www.rfc-editor.org/rfc/rfc9111.html#section-5.2.2.5) | no-store cache semantics; not universal send MUST, not reliable privacy/erase guarantee |
| DISPOSITION | [RFC6266 June2011; RFC Editor lists Proposed Standard](https://www.rfc-editor.org/rfc/rfc6266.html#section-4.3) | attachment filename/filename* representation; current browser-support blanket not claimed |
| PARAMETERS | [RFC8187 September2017; Proposed Standard; obsoletes5987](https://www.rfc-editor.org/rfc/rfc8187.html#section-3.2) | HTTP extended parameter encoding; helper historical RFC5987/browser2011 prose not current conformance proof |
| WS | [RFC6455 December2011](https://www.rfc-editor.org/rfc/rfc6455.html) | handshake/framing separate protocol; application expiry/revoke/envelope require explicit local contract |
| SSE | [WHATWG HTML living standard §9.2, read2026-10-31](https://html.spec.whatwg.org/multipage/server-sent-events.html) | text/event-stream parsing/EventSource/reconnect model; finite download or client.stream is not browser SSE |
| MULTIPART | [RFC7578 July2015](https://www.rfc-editor.org/rfc/rfc7578.html#section-4) | multipart/form-data boundary/parts; request encoding is separate from JSON response and domain admission |
| CALENDAR | [RFC5545 September2009 §3.8.7.4](https://www.rfc-editor.org/rfc/rfc5545.html#section-3.8.7.4) | iCalendar revision sequence semantics; application owns increment/transaction, no claim of all-client interoperability |

RFC8187 obsoletes5987; RFC Editor сейчас перечисляет6266/8187 как Proposed Standard. Историческая helper docstring оRFC5987 и «все браузеры с2011» сохранена как source description, не современное normative/browser proof. RFC9457 status member **если он формируется** должен совпадать с HTTPstatus; no-store/nosniff/requestId — выбранная политика приложения, не универсальные MUST любого ответа. OpenAPI описывает ограничения, но не исполняет ACL. Security scopes в одном requirement не заменяют текущие grants. Webhooks/industry/cloud integration используют отдельные domain contracts, не подменяются websocket или общей OpenAPI сущностью.

## Source gaps и решения владельца

Ни один gap не объявляет доказанную эксплуатацию или production leak. Полные chains с SHA/lines, current-vs-historical, negative characterization, compatibility/rollback и priority находятся вJSON.

| Gap / priority | Текущий source факт | Следующий bounded owner step |
|---|---|---|
| CP-01 / P2 | initial JWT session_valid; accepted meta lacks exp/tv; ordinary ping/nonchat delivery no fresh session check. Task/ticket delivery guards remain independent | ROOT policy decision on accepted-WS lifetime/revoke, then one chat session/channel admission owner; retain task/ticket/history owner calls, no duplicate ACL |
| CP-02 / P2 conditional | known WS query logging gap fixed; three capability token PATH families are outside _PRIVATE query rules and exact chat path. safe_target keeps ordinary path without query | separate ROOT-reviewed narrow path-capability redaction proposal in existing safe_target; closed known formats and exact path shapes, not generic URL parsing/ACL |
| CP-03 / P3 selected next patch | shared XLSX Response sets only Content-Disposition; conditional_get ignores non-JSON. Exact7callers S30-S36 | ONLY add Cache-Control private,no-store to existing xlsx_response success header after new ROOT implementation decision; no new framework |
| CP-04 / P2 conditional, fuel deferred | HTTPX.content/text buffered, partial hop-header filtering, HTML rewritten with upstream Content-Type/validators and idle cookie renewal; no streaming/cancellation relay | own station console adapter contract; ROOT/domain owner chooses finite-only or separate streaming path, supported header/redirect/size semantics before code |
| CP-05 / P2 integrity characterization | calendar paper validates company/event/paper/file relation, but unlike task attachment has no explicit SourceFile.company_id condition in paper_file | characterize synthetic mismatched CalendarPaper/SourceFile association first; ROOT decides whether explicit tenant guard is compatible before any patch |
| CP-06 / P2 business decision required | week removes money rows when business.sales invisible; objects has item gate; operations branch uses product gate and emits expected cost; _sees_money is computed but not used there | domain passport decision for revenue vs costs and business.ops before any code; do not strengthen/weaken accepted P8 semantics in this revision |
| CP-07 / P3 protocol characterization | persisted bounded organizer SEQUENCE replaces old hardcoded/default sequence path; guest nullable expiry, feed rotation and participant JWT are three different admissions | update domain passport to exact persisted sequence/UID/UTC/cancel semantics and existing revision0002 receipt; no migration edits here |

CP-06 требует осторожности: `_sees_money` описывает выручку, `_ops_snapshot` — ожидаемые расходы. Operations endpoint и export сейчас используют product gate. Это business-policy unknown, не автоматическое доказательство нарушения revenue ACL; accepted P8 не меняется. CP-05 требует синтетической association проверки до решения об усилении file tenant gate. CP-02 касается capability в path, **отдельно** от уже исправленного WS query logging; реальные URL/logs не читались.

## Один следующий codepatch proposal: private XLSX response

Production scope будущего task — **только `app/services/export_files.py::xlsx_response`**: добавить `Cache-Control: private, no-store` в существующий success Response. Тот же owner/байты/MIME/filename/disposition/status; caller admission/query/filters/audit/commit остаются прежними. Это локальное privacy решение, не RFC universalMUST. ROOT pre-read подтвердил точные7calls: corporate1/reconciliation1/charge_sessions3/docs2. Код здесь не реализован.

| ID | Caller method/path | Source line |
|---|---|---|
| S30 | `GET /api/corporate/billing-export` | `corporate_router.py`:119 |
| S31 | `GET /api/charge-sessions/export` | `charge_sessions_router.py`:658 |
| S32 | `GET /api/charge-sessions/export/pivot` | `charge_sessions_router.py`:740 |
| S33 | `GET /api/charge-sessions/export/monthly-matrix` | `charge_sessions_router.py`:772 |
| S34 | `GET /api/reconciliation/export` | `reconciliation_router.py`:91 |
| S35 | `GET /api/docs/reports/export` | `docs_router.py`:1905 |
| S36 | `GET /api/docs/export` | `docs_router.py`:2088 |

Вне patch: native DataEntry XLSX/CSV StreamingResponse, store ZIP/Response alias/HTML, direct sites Response, stored FileResponse, product generator, capability files, Pulse CSV, ICS и docs CSV branch. Не вводить generic delivery framework, не менять filename sanitizer, новые quotas, SQL, profile, ACL, dependencies, routes или schema. Helper сам не пишет SQL; вызывающие exports могут add audit и schedule guard, это сохраняется.

Предложенная meaningful матрица: fixed two-company rows; current-role/product/foreign/revoke refusals без workbook bytes; семь настоящих native XLSX success outputs со значениями/Unicode filename/MIME/status, source body branch identity; helper direct response header; допустимые audit/commit effects и отсутствие delivery. Сохранить существующие assertions `test_docs_reports::test_выгрузка_отчёта_открывается_книгой` и `test_выгрузка_реестра_держит_отбор`; остальных7callers future selection/fixtures ROOT определит до frozen execution. Не зеркалировать SQL predicates в тесте. Разный ZIP timestamp книги не выдавать за изменение табличных данных; byte comparison требует согласованного fixture provenance.

Для **этого task** ROOT validation только Git/stdlib AST/hash/JSON:44/75identity, source manifests, wholefile/function distinction, aliases/mount/factories, old inputs unchanged, JSON≤8MiB и diffcheck. Runtimeworker0. Для будущего patch нужен новый exactsource/tests/support/schema/runner/argv/env/fullIDs/counts freeze, candidate77 -I-S-B, fresh synthetic DB `api_protocol_xlsx_privacy_test_20261031` на127.0.0.1:33546, fourprivate0700roots, pool2/overflow0, statement20s/lock2s/idle30s/connect10s/command30s; CPU600/wall650/AS3GiB/FD256/FSIZE2MiB/scratch128MiB4096files/capture4000. FiveIPv6restore/nativePGmetadata16/env/process/net/write/source guards; terminal delivery capture; normalDROP только ROOT ownDB послеreap/connections0/exists0. Это proposal, не разрешение запуска сейчас.

## Результат и оставшаяся работа

Production0/runtime0, никаких новых imports/tests/SQL/Node/application HTTP/secret reads/deploy. Были только source/Git/AST/hash/compile и чтение official standards; ошибки draft enrichment syntax исправлены до отчётов, application не исполнялось. ROOT source review принят `msg_867d3fbaa9ca`; report-only уточнение row-vs-unique counters разрешено `msg_a776de7fbe89`, без изменения источников/proofs. Нужны отдельные protocol owner decisions и targeted actual characterization; M01/M09, M00–M19+11, current CI и release не закрыты.
