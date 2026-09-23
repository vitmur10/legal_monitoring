LABELS = {
    "DRAFT": "Проєкт", "ADOPTED": "Прийнятий", "SIGNED": "Підписаний",
    "PUBLISHED": "Опублікований", "EFFECTIVE": "Чинний", "EXPIRED": "Втратив чинність",
    "NON_CURRENT": "Неактуальний", "EXPLANATION": "Офіційне роз’яснення",
    "OTHER": "Інше", "NOT_DETERMINED": "Не визначено",
    "CRITICAL": "Критична", "HIGH": "Висока", "MEDIUM": "Середня", "LOW": "Низька",
    "RECOMMENDED": "Рекомендовано", "OPTIONAL": "За бажанням", "NOT_RECOMMENDED": "Не рекомендовано",
    "VAT": "ПДВ", "CORPORATE_INCOME_TAX": "Податок на прибуток", "PIT": "ПДФО",
    "MILITARY_TAX": "Військовий збір", "SSC": "ЄСВ", "EXCISE": "Акциз",
    "SINGLE_TAX": "Єдиний податок", "TRANSFER_PRICING": "Трансфертне ціноутворення",
    "CFC": "КІК", "INTERNATIONAL_TAX": "Міжнародне оподаткування",
    "CRS": "Обмін фінансовою інформацією", "BEPS": "Протидія розмиванню податкової бази",
    "TAX_AUDIT": "Податкові перевірки", "PENALTIES": "Штрафи", "TAX_REPORTING": "Податкова звітність",
    "PN_RK": "Податкові накладні та розрахунки коригування", "SMKOR": "Моніторинг податкових накладних",
    "RRO_PRRO": "РРО та ПРРО", "SAF_T_UA": "Стандартний аудиторський файл", "E_AUDIT": "Електронний аудит",
    "ACCOUNTING": "Бухгалтерський облік", "FINANCIAL_REPORTING": "Фінансова звітність",
    "PRIMARY_DOCUMENTS": "Первинні документи", "IFRS": "МСФЗ", "EU_TAX_INTEGRATION": "Податкова євроінтеграція",
    "DAC": "Адміністративна співпраця", "E_INVOICING": "Електронні рахунки", "OTHER_RELEVANT": "Інші релевантні теми",
    "ALL_TAXPAYERS": "Усі платники податків", "LEGAL_ENTITIES": "Юридичні особи", "VAT_PAYERS": "Платники ПДВ",
    "CORPORATE_INCOME_TAX_PAYERS": "Платники податку на прибуток", "FOP": "ФОП", "EMPLOYERS": "Роботодавці",
    "TAX_AGENTS": "Податкові агенти", "SINGLE_TAX_PAYERS": "Платники єдиного податку", "LARGE_TAXPAYERS": "Великі платники",
    "FINANCIAL_INSTITUTIONS": "Фінансові установи", "INTERNATIONAL_BUSINESS": "Міжнародний бізнес",
    "CONTROLLED_TRANSACTION_PARTICIPANTS": "Учасники контрольованих операцій", "CFC_OWNERS": "Власники КІК",
    "SPECIFIC_INDUSTRY": "Окрема галузь", "news": "Новина", "explanation": "Роз’яснення",
    "law": "Закон", "order": "Наказ", "resolution": "Постанова",
    "ZIR_CONSULTATION": "Консультація ЗІР", "LAW": "Закон", "ORDER": "Наказ", "RESOLUTION": "Постанова",
}


def label(value: str | None) -> str:
    return LABELS.get(value or "", "Не визначено" if not value else "Інше" if value.isascii() else value)
