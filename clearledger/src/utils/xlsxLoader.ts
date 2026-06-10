type XlsxModule = typeof import('xlsx');

let cachedXlsx: XlsxModule | null = null;

export async function loadXlsx(): Promise<XlsxModule> {
  if (cachedXlsx) {
    return cachedXlsx;
  }

  const xlsxModule = await import('xlsx');
  cachedXlsx = xlsxModule;
  return xlsxModule;
}
