import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowUpRight, Download, Loader2, MessageSquare, Play, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { useCompany } from '@/contexts/CompanyContext'
import { useOpenApp } from '@/hooks/useOpenApp'
import { ELSY_VIEWS, elsyView, type ElsyView } from '@/config/elsyViews'
import { VendorSupportPanel } from '@/components/support/VendorSupportPanel'
import { listPartnerSpaces, listTopics, partnerFileUrl, TOPIC_STATE_NAME } from '@/services/partnerSpaceService'
import { listSsoApps } from '@/services/ssoService'
import { getVendorCatalog, getVendorDocuments, launchVendorDemo, type VendorProduct } from '@/services/vendorService'
import { openAuthAttachment } from '@/lib/authFiles'
import { formatDateTime } from '@/lib/formatDate'
import { cn } from '@/lib/utils'

function Notice({ title, children, retry }: {
  title: string; children: React.ReactNode; retry?: () => void
}) {
  return <Card role={retry ? 'alert' : 'status'} className="shadow-none">
    <CardHeader><CardTitle>{title}</CardTitle><CardDescription>{children}</CardDescription></CardHeader>
    {retry && <CardContent><Button variant="outline" onClick={retry}><RefreshCw />Попробовать ещё раз</Button></CardContent>}
  </Card>
}

function Loading() {
  return <div aria-label="Загрузка" role="status" className="flex flex-col gap-4">
    <Skeleton className="h-8 w-56" /><Skeleton className="h-32 w-full" /><Skeleton className="h-32 w-full" />
  </div>
}

function ProductImage({ product }: { product: VendorProduct }) {
  const [failed, setFailed] = useState(false)
  if (!product.image || failed) return null
  return <img src={product.image} alt={`Интерфейс ${product.name || product.title}`}
    loading="lazy" onError={() => setFailed(true)}
    className="aspect-video w-full rounded-lg border border-border object-contain bg-card" />
}

export function ElsyPage() {
  const { companyId } = useCompany()
  return <ElsyWorkspace key={companyId} />
}

function ElsyWorkspace() {
  const { companyId, company, canApp } = useCompany()
  const [params, setParams] = useSearchParams()
  const view = elsyView(params.get('view'))
  const mobileNav = useRef<HTMLElement>(null)
  const productCode = params.get('product')
  const topicCode = params.get('topic')
  const [search, setSearch] = useState('')
  const [demoBusy, setDemoBusy] = useState(false)
  const [demoError, setDemoError] = useState('')
  const { openApp, busy: appBusy } = useOpenApp()
  const partners = useQuery({ queryKey: ['partner-spaces', companyId],
    queryFn: () => listPartnerSpaces(companyId), enabled: !!companyId, staleTime: 60_000 })
  const vendors = partners.data?.items.filter((item) => item.role === 'vendor' && item.isActive) || []
  const vendor = params.get('vendor') ? vendors.find((item) => item.code === params.get('vendor')) : vendors[0]
  const vendorCode = vendor?.code || ''
  const ready = !!companyId && !!vendor?.linked
  useEffect(() => {
    if (mobileNav.current?.offsetParent) {
      mobileNav.current.querySelector('[aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'center' })
    }
  }, [view, ready])
  const catalog = useQuery({ queryKey: ['vendor-catalog', companyId, vendorCode],
    queryFn: () => getVendorCatalog(vendorCode, companyId), enabled: ready, staleTime: 60_000, retry: 1 })
  const apps = useQuery({ queryKey: ['elsy-apps', companyId],
    queryFn: () => listSsoApps(companyId), enabled: !!companyId })
  const topics = useQuery({ queryKey: ['partner-topics', vendorCode, companyId],
    queryFn: () => listTopics(vendorCode, companyId), enabled: ready && view === 'overview',
    refetchInterval: 20_000 })
  const documents = useQuery({ queryKey: ['vendor-documents', companyId, vendorCode],
    queryFn: () => getVendorDocuments(vendorCode, companyId),
    enabled: ready && view === 'documents' && canApp('docs') })
  const products = catalog.data?.products || []
  const selected = products.find((item) => item.code === productCode)
  const services = (apps.data?.apps || []).filter((app) => app.code !== 'elsy'
    && app.layer === 'app' && canApp(app.code)
    && (!apps.data?.allowed_apps || apps.data.allowed_apps.includes(app.code)))
  const connected = (product: VendorProduct) => services.find((app) => product.appCodes.includes(app.code))
  const href = (next: ElsyView, extra: Record<string, string> = {}) => {
    const query = new URLSearchParams({ view: next, ...(vendorCode ? { vendor: vendorCode } : {}), ...extra })
    return `/elsy?${query}`
  }
  const go = (next: ElsyView, extra: Record<string, string> = {}) => {
    setDemoError('')
    setParams(new URLSearchParams({ view: next, ...(vendorCode ? { vendor: vendorCode } : {}), ...extra }))
  }
  const ask = (product?: VendorProduct, action = 'Обсудить применение') => {
    go('work', { topic: 'new', ...(product ? { product: product.code, action } : {}) })
  }
  const launch = async (product: VendorProduct) => {
    if (!vendor || !product.demo || demoBusy) return
    const popup = window.open('about:blank', '_blank')
    if (!popup) { setDemoError('Разрешите открытие новой вкладки для демонстрации и повторите попытку'); return }
    popup.opener = null
    popup.document.title = 'Открываем демонстрацию'
    popup.document.body.textContent = 'Готовим доступ к демонстрации…'
    setDemoBusy(true)
    setDemoError('')
    try {
      const result = await launchVendorDemo(vendor.code, companyId, product.demo.code)
      const url = new URL(result.url)
      if (!['https:', 'http:'].includes(url.protocol)) throw new Error('Не удалось открыть адрес демонстрации')
      popup.location.replace(url.href)
    } catch (error) {
      popup.close()
      setDemoError((error as Error).message || 'Не удалось открыть показ. Попробуйте ещё раз или напишите нам')
    } finally { setDemoBusy(false) }
  }
  const catalogNotice = catalog.isPending ? <Loading /> : catalog.isError
    ? <Notice title="Каталог сейчас недоступен" retry={() => void catalog.refetch()}>
        Обращения и документы доступны отдельно. Можно написать нам по интересующему продукту.
      </Notice> : null

  if (partners.isPending) return <div className="p-4 md:p-6"><Loading /></div>
  if (partners.isError) return <div className="p-4 md:p-6"><Notice title="Не удалось открыть связь с ЭЛСИ"
    retry={() => void partners.refetch()}>Проверьте соединение и повторите попытку.</Notice></div>
  if (!vendor) return <div className="p-4 md:p-6"><Notice title="Связь с поставщиком не найдена">
    Попросите администратора пространства проверить подключение к ЭЛСИ.
  </Notice></div>
  if (!vendor.linked) return <div className="p-4 md:p-6"><Notice title="Связь с ЭЛСИ готовится">
    После настройки здесь появятся обращения, документы и демонстрации продуктов.
  </Notice></div>

  return <div data-elsy-surface className="flex min-h-0 flex-1 flex-col">
    <nav ref={mobileNav} aria-label="Разделы Элси+" className="flex shrink-0 gap-1 overflow-x-auto border-b border-border bg-card p-2 md:hidden">
      {ELSY_VIEWS.map((item) => <Button key={item.code} asChild size="sm"
        variant={view === item.code ? 'default' : 'ghost'} className="shrink-0">
        <Link to={href(item.code)} aria-current={view === item.code ? 'page' : undefined}>{item.label}</Link>
      </Button>)}
    </nav>
    {vendors.length > 1 && <div className="flex items-center gap-3 border-b border-border bg-card px-4 py-2">
      <label htmlFor="elsy-vendor" className="text-sm">Поставщик</label>
      <select id="elsy-vendor" value={vendorCode} className="min-h-10 rounded-md border border-input bg-background px-3 text-sm"
        onChange={(event) => setParams({ view, vendor: event.target.value })}>
        {vendors.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
      </select>
    </div>}
    <div className={cn('min-h-0 flex-1', view === 'work' ? 'flex flex-col' : 'overflow-y-auto p-4 md:p-6')}>
      {view === 'work' && <div className="flex min-h-[32rem] flex-1 flex-col">
        {selected && <div className="border-b border-border bg-card px-4 py-2">
          <Button variant="ghost" size="sm" onClick={() => go('products', { product: selected.code })}>
            <ArrowLeft />К продукту {selected.name}
          </Button>
        </div>}
        {productCode && catalog.isPending ? <Loading /> : <VendorSupportPanel key={`${companyId}:${vendorCode}:${topicCode || ''}:${selected?.code || productCode || ''}:${selected?.title || ''}:${params.get('action') || ''}`}
          vendor={vendor} companyId={companyId} relationship openTopicCode={topicCode}
          subject={selected ? { kind: 'product', ref: selected.code,
            label: `${params.get('action') || 'Обсудить применение'}: ${selected.title}` }
            : productCode ? { kind: 'product', ref: productCode, label: `Вопрос о продукте: ${productCode}` } : null} />}
      </div>}

      {view === 'overview' && <div className="mx-auto flex max-w-6xl flex-col gap-7">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex max-w-2xl flex-col gap-2"><h1 className="text-xl font-semibold">Продолжим работу вместе</h1>
            <p className="text-sm leading-relaxed text-muted-foreground">Обращения, документы и продукты ЭЛСИ для {company.shortName || company.name}.</p></div>
          <Button onClick={() => ask()}><MessageSquare />Написать нам</Button>
        </div>
        <section className="flex flex-col gap-3" aria-labelledby="elsy-current-work">
          <div className="flex items-center justify-between gap-3"><h2 id="elsy-current-work" className="font-semibold">Текущая работа</h2>
            <Button asChild variant="ghost" size="sm"><Link to={href('work')}>Все обращения<ArrowUpRight /></Link></Button></div>
          {topics.isPending ? <Loading /> : topics.isError ? <Notice title="Обращения не загрузились" retry={() => void topics.refetch()}>
            Повторите попытку, чтобы увидеть актуальное состояние работы.
          </Notice> : topics.data?.items.filter((topic) => !['resolved', 'closed'].includes(topic.state)).length ?
            <div className="divide-y divide-border rounded-xl border border-border bg-card">
              {topics.data.items.filter((topic) => !['resolved', 'closed'].includes(topic.state)).slice(0, 5).map((topic) =>
                <Link key={topic.code} to={href('work', { topic: topic.code })}
                  className="flex flex-wrap items-center justify-between gap-3 px-4 py-4 transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring">
                  <div className="flex min-w-0 flex-1 flex-col gap-1"><span className="break-words text-sm font-medium">{topic.title}</span>
                    <span className="text-xs text-muted-foreground">{topic.number ? `№ ${topic.number} · ` : ''}{topic.subjectLabel || vendor.name}</span></div>
                  <Badge variant={topic.state === 'waiting' ? 'default' : 'secondary'}>{TOPIC_STATE_NAME[topic.state]}</Badge>
                </Link>)}
            </div> : <Notice title="Открытых обращений пока нет">Можно обсудить текущую задачу или познакомиться с другими нашими продуктами.</Notice>}
        </section>
        <section className="flex flex-col gap-4" aria-labelledby="elsy-discover">
          <div className="flex flex-wrap items-center justify-between gap-2"><h2 id="elsy-discover" className="font-semibold">Что ещё поможет в работе</h2>
            <Button asChild variant="ghost" size="sm"><Link to={href('products')}>Все продукты и демо<ArrowUpRight /></Link></Button></div>
          {catalogNotice || <div className="divide-y divide-border">
            {products.filter((product) => !connected(product)).slice(0, 3).map((product) =>
              <Link key={product.code} to={href('products', { product: product.code })}
                className="grid gap-2 py-4 transition-colors hover:text-primary sm:grid-cols-[12rem_1fr]">
                <span className="font-medium">{product.title}<span className="ml-2 text-xs text-muted-foreground">{product.name}</span></span>
                <span className="max-w-3xl text-sm leading-relaxed text-muted-foreground">{product.description}</span>
              </Link>)}
          </div>}
        </section>
      </div>}

      {view === 'products' && <div className="mx-auto flex max-w-6xl flex-col gap-5">
        {catalogNotice || (productCode ? selected ? <>
          <Button variant="ghost" className="self-start" onClick={() => go('products')}><ArrowLeft />Все продукты</Button>
          <div className="grid items-start gap-7 lg:grid-cols-[1fr_1.1fr]">
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-2"><h1 className="text-2xl font-semibold">{selected.title}</h1>
                <span className="text-sm text-muted-foreground">{selected.name}</span></div>
              <p className="max-w-prose text-sm leading-relaxed">{selected.description}</p>
              <div className="flex flex-wrap gap-2"><Badge variant="secondary">{selected.category}</Badge>
                {selected.stage === 'announced' && <Badge variant="outline">В разработке</Badge>}
                {connected(selected) && <Badge>Подключён в пространстве</Badge>}</div>
              {connected(selected) && <Button disabled={!!appBusy} className="self-start" onClick={() => void openApp(connected(selected)!)}>
                <ArrowUpRight />Открыть мой сервис</Button>}
              {selected.demo?.ready && selected.demo.allowed ? <>
                <p className="text-sm text-muted-foreground">{selected.demo.description} Показ откроется в отдельной вкладке на учебных данных.</p>
                <Button disabled={demoBusy} className="self-start" onClick={() => void launch(selected)}>
                  {demoBusy ? <Loader2 className="animate-spin" /> : <Play />}Открыть демо</Button>
              </> : <p className="text-sm text-muted-foreground">{selected.stage === 'announced'
                ? 'Разработка ещё не доступна для самостоятельного показа. Расскажите, где она могла бы помочь.'
                : 'Подберём показ под вашу задачу. Напишите, что хотите посмотреть.'}</p>}
              {demoError && <p role="alert" className="text-sm text-destructive">{demoError}</p>}
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => ask(selected, 'Обсудить применение')}><MessageSquare />Обсудить применение</Button>
                {!(selected.demo?.ready && selected.demo.allowed) && selected.stage !== 'announced'
                  && <Button onClick={() => ask(selected, 'Договориться о показе')}>Договориться о показе</Button>}
              </div>
            </div>
            <ProductImage key={selected.code} product={selected} />
          </div>
        </> : <Notice title="Продукт не найден">Он мог быть снят с каталога. <Link className="underline" to={href('products')}>Открыть все продукты</Link></Notice>
          : <>
            <div className="flex max-w-3xl flex-col gap-2"><h1 className="text-xl font-semibold">Найдите решение для своей задачи</h1>
              <p className="text-sm leading-relaxed text-muted-foreground">Познакомьтесь с нашими разработками, попробуйте демо и обсудите применение в своём пространстве.</p></div>
            <div className="flex max-w-md flex-col gap-2"><label htmlFor="elsy-products-search" className="text-sm">Найти продукт или задачу</label>
              <Input id="elsy-products-search" type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Например, учёт или поддержка" /></div>
            <div className="divide-y divide-border">
              {products.filter((product) => `${product.title} ${product.name} ${product.description}`.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')))
                .map((product) => <Link key={product.code} to={href('products', { product: product.code })}
                  className="grid items-start gap-4 py-5 transition-colors hover:text-primary focus-visible:outline-2 focus-visible:outline-ring sm:grid-cols-[13rem_1fr_auto]">
                  <div className="flex flex-col gap-1"><span className="font-semibold">{product.title}</span><span className="text-xs text-muted-foreground">{product.name} · {product.category}</span></div>
                  <p className="max-w-prose text-sm leading-relaxed text-muted-foreground">{product.description}</p>
                  <Badge variant="secondary" className="justify-self-start">{connected(product) ? 'Подключён'
                    : product.stage === 'announced' ? 'В разработке' : product.demo?.ready && product.demo.allowed ? 'Есть демо' : 'Показ с нами'}</Badge>
                </Link>)}
            </div>
            {!products.some((product) => `${product.title} ${product.name} ${product.description}`.toLocaleLowerCase('ru').includes(search.toLocaleLowerCase('ru')))
              && <Notice title="По этому запросу ничего не найдено">Попробуйте другое слово или обсудите задачу с нами.</Notice>}
          </>)}
      </div>}

      {view === 'documents' && <div className="mx-auto flex max-w-5xl flex-col gap-5">
        <p className="max-w-3xl text-sm text-muted-foreground">Документы и материалы, которые наша команда передала в обращениях. Каждый файл сохраняет связь с разговором.</p>
        {!canApp('docs') ? <Notice title="Нужен доступ к документам">Попросите администратора пространства предоставить доступ к Треку.</Notice>
          : documents.isPending ? <Loading /> : documents.isError ? <Notice title="Документы не загрузились" retry={() => void documents.refetch()}>
            Повторите попытку. Обращения доступны в разделе «Работа с нами».
          </Notice> : documents.data?.items.length ? <div className="divide-y divide-border rounded-xl border border-border bg-card">
            {documents.data.items.map((document) => <article key={document.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
              <div className="flex min-w-0 flex-1 flex-col gap-2"><h2 className="break-words text-sm font-medium">{document.name}</h2>
                <p className="text-xs text-muted-foreground">{document.author}{document.createdAt ? ` · ${formatDateTime(document.createdAt)}` : ''} · {Math.max(1, Math.round(document.size / 1024))} КБ</p>
                {document.topicCode && <Link className="text-sm text-primary underline underline-offset-4" to={href('work', { topic: document.topicCode })}>{document.topicTitle || 'Обсудить документ'}</Link>}
              </div>
              <Button variant="outline" size="sm" onClick={() => void openAuthAttachment(partnerFileUrl(document.id, companyId))}><Download />Открыть</Button>
            </article>)}
          </div> : <Notice title="Выданных файлов пока нет">Документы и материалы появятся здесь после передачи нашей командой.</Notice>}
      </div>}

      {view === 'services' && <div className="mx-auto flex max-w-5xl flex-col gap-5">
        <p className="max-w-3xl text-sm text-muted-foreground">Рабочие приложения, подключённые к вашему пространству и доступные по вашей роли.</p>
        {apps.isPending ? <Loading /> : apps.isError ? <Notice title="Состав приложений не загрузился" retry={() => void apps.refetch()}>
          Повторите попытку, чтобы увидеть подключённые сервисы.
        </Notice> : services.length ? <div className="divide-y divide-border">
          {services.map((app) => <article key={app.code} className="flex flex-wrap items-center justify-between gap-4 py-4">
            <div className="flex min-w-0 max-w-3xl flex-1 flex-col gap-1"><h2 className="font-medium">{app.name}</h2><p className="text-sm text-muted-foreground">{app.description}</p></div>
            <Button variant="outline" disabled={!!appBusy} onClick={() => void openApp(app)}><ArrowUpRight />Открыть</Button>
          </article>)}
        </div> : <Notice title="Рабочие приложения пока не подключены">В каталоге можно выбрать подходящий продукт и обсудить его применение.</Notice>}
        <Button asChild variant="outline" className="self-start"><Link to={href('products')}>Посмотреть другие продукты</Link></Button>
      </div>}

      {view === 'help' && <div className="mx-auto flex max-w-4xl flex-col gap-5">
        <div className="flex flex-wrap items-start justify-between gap-4"><p className="max-w-xl text-sm text-muted-foreground">Ответы о продуктах и работе с ЭЛСИ. Для вопроса по своей задаче напишите нашей команде.</p>
          <Button onClick={() => ask()}><MessageSquare />Задать вопрос</Button></div>
        {catalogNotice || <div className="divide-y divide-border">{catalog.data?.help.map((item) => <details key={item.question} className="py-4">
          <summary className="cursor-pointer text-sm font-medium">{item.question}</summary><p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">{item.answer}</p>
        </details>)}</div>}
        <Link to="/info" className="text-sm text-primary underline underline-offset-4">Инструкции по работе в пространстве</Link>
      </div>}
    </div>
  </div>
}
