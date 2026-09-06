---
timestamp: 2026-08-21T07-11-46Z
slug: src-components-workspace-accountingpanels-tsx
---
{
  "target": "src/components/workspace/AccountingPanels.tsx",
  "surface": "Приложение «Эксплуатация» — Мониторинг, Оборудование, Хозяйство",
  "mode": "operate",
  "method": "degraded: single-context (политика сессии запрещает субагентов без явной просьбы)",
  "date": "2026-08-21",
  "applicable_max": 40,
  "na_heuristics": [],
  "scores": {
    "visibility_of_system_status": 3,
    "match_system_real_world": 4,
    "user_control_freedom": 3,
    "consistency_standards": 3,
    "error_prevention": 3,
    "recognition_rather_than_recall": 2,
    "flexibility_efficiency": 2,
    "aesthetic_minimalist": 2,
    "error_recovery": 3,
    "help_documentation": 3
  },
  "total": 28,
  "detector": { "findings": 0, "scanned": ["src/components/balance", "src/components/equipment"] },
  "issues": [
    {
      "severity": "P0",
      "title": "Данные нельзя загрузить из интерфейса",
      "detail": "Ручка POST /api/ops/payments/upload существовала, кнопки не было; пустое состояние отсылало пользователя к адресу API.",
      "status": "исправлено 21.08.2026"
    },
    {
      "severity": "P1",
      "title": "Нет разреза по контрагентам в кассовом факте",
      "detail": "Объекты не связаны бухгалтерским номером, а единственный доступный разрез не был показан.",
      "status": "исправлено 21.08.2026"
    },
    {
      "severity": "P1",
      "title": "Не видно происхождения цифры",
      "detail": "source_label и loaded_at хранились, но на экране не показывались.",
      "status": "исправлено 21.08.2026"
    },
    {
      "severity": "P2",
      "title": "Годовые и месячные строки в одной таблице",
      "detail": "Разная достоверность в одном списке создавала ложную точность: у годов нет начислений.",
      "status": "исправлено 21.08.2026"
    },
    {
      "severity": "P2",
      "title": "Семь пунктов в «Хозяйстве», три отвечают на близкие вопросы",
      "detail": "Закрытие месяца, Затраты объектов, Оплаты. Решение владельца 21.08.2026 — оставить раздельно.",
      "status": "решено оставить как есть"
    },
    {
      "severity": "P3",
      "title": "Разрозненные пустые состояния разделов",
      "detail": "Мониторинг, Оборудование и Хозяйство объясняют отсутствие данных разными словами и на разном уровне подробности.",
      "status": "открыто"
    }
  ]
}
