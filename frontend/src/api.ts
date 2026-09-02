// Capa de acceso a la API del backend (proxyada por Vite a FastAPI).

export interface Provider {
  id: string;
  name: string;
  document: string;
}

export interface Product {
  id: string;
  name: string;
}

export interface CheckedItem {
  descripcion: string;
  cantidad: number | null;
  total: number | null;
  reconocido: boolean;
  product_id: string | null;
  product_name: string | null;
  factor: number; // unidades de inventario por unidad facturada (six pack = 6)
}

export interface CheckResult {
  provider_id: string;
  total: number;
  reconocidos: number;
  pendientes: number;
  items: CheckedItem[];
}

export interface TirillaItem {
  descripcion: string;
  cantidad?: number | null;
  total?: number | null;
}

export interface CacheStatus {
  products: number;
  providers: number;
  products_age: number | null;
  providers_age: number | null;
  ttl: number;
}

export interface ExtraccionItem {
  descripcion: string;
  cantidad: number;
  total: number;
}

export interface Extraccion {
  proveedor: { nombre_tirilla: string; nit: string };
  documento: { numero: string; fecha: string; pagado: boolean; forma_pago?: string; tipo?: string };
  items: ExtraccionItem[];
  totales: { total_pagar: number };
  cuadra: boolean;
}

export interface ExtractResult {
  extraccion: Extraccion;
  proveedor_sugerido: Provider | null;
}

export interface MovimientoResult {
  ok: boolean;
  movement_id: string | null;
  invoice_number: string;
  total: number;
  items: number;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResult {
  extraccion: Extraccion;
  proveedor_sugerido: Provider | null;
  respuesta: string;
}

// ---- Gastos ----
export interface TipoGasto {
  id: string;
  name: string;
}

export interface Responsable {
  id: string;
  name: string;
}

export interface GastoExtraccion {
  proveedor: { nombre_tirilla: string; nit: string };
  documento: { numero: string; fecha: string };
  concepto: string;
  forma_pago?: string;
  subtotal: number;
  impuestos: number;
}

export interface GastoExtractResult {
  gasto: GastoExtraccion;
  proveedor_sugerido: Provider | null;
  tipo_sugerido: string | null;
  responsable_sugerido: string | null;
}

export interface GastoChatResult extends GastoExtractResult {
  respuesta: string;
}

export interface CrearGastoResult {
  ok: boolean;
  expense_id: string | null;
  total: number;
}

// ---- Beneficiarios recurrentes (nómina y pagos que se repiten) ----
export type Periodicidad = "semanal" | "quincenal" | "mensual" | "libre";

export interface Recurrente {
  id: string;
  nombre: string;
  concepto: string; // texto que se escribe igual en todos sus gastos
  type_expense_id: string;
  provider_id: string | null;
  forma_pago: string;
  sale_de_caja: boolean;
  monto_sugerido: number;
  periodicidad: Periodicidad;
  activo: boolean;
  notas: string;
  ultimo_pago: string | null; // YYYY-MM-DD
  dias_desde_ultimo: number | null;
  vencido: boolean; // pasó el periodo nominal; es un aviso, no dispara nada
}

/** Sugerencia leída del historial de Loggro; aún no está guardada. */
export interface SugerenciaRecurrente {
  id: string;
  nombre: string;
  veces: number;
  ultimo_pago: string | null;
  dias_desde_ultimo: number | null;
  monto_sugerido: number; // mediana: los montos de una misma persona oscilan mucho
  monto_min: number;
  monto_max: number;
  type_expense_id: string | null;
  tipo_nombre: string;
  ya_registrado: boolean;
}

export interface LoteLineaResult {
  recurrente_id: string;
  nombre: string;
  ok: boolean;
  expense_id?: string | null;
  total?: number;
  error?: string;
}

export interface LoteResult {
  ok: boolean;
  creados: number;
  fallidos: number;
  total: number;
  fecha: string;
  detalle: LoteLineaResult[];
}

// ---- Utilidad (ventas vs compras + gastos) ----
export interface PeriodoUtilidad {
  periodo: string; // YYYY-MM
  ventas: number;
  compras: number;
  gastos: number;
  salidas: number; // compras + gastos
  utilidad: number;
  margen: number; // % sobre la venta
  peso_salidas: number; // % que pesan las salidas sobre la venta
  n_facturas: number;
  n_compras: number;
  n_gastos: number;
}

/** Aviso de que la información podría estar incompleta. No es un veredicto. */
export interface AlertaUtilidad {
  tipo: "fecha_imposible" | "salidas_bajas" | "dias_sin_salidas" | "recurrente_vencido";
  severidad: "alta" | "media";
  titulo: string;
  detalle: string;
  periodo?: string;
  items?: (string | Record<string, string | number>)[];
}

export interface UtilidadResult {
  desde: string;
  hasta: string;
  corte_jornada: number;
  periodos: PeriodoUtilidad[];
  total: Omit<PeriodoUtilidad, "periodo" | "peso_salidas">;
  alertas: AlertaUtilidad[];
}

/** `aviso` llega cuando el guardado se quedó local porque el KV no respondió. */
export interface GuardadoResult {
  ok: boolean;
  id: string;
  persistencia: "kv" | "local";
  aviso?: string;
}

// ---- Cartera (créditos de clientes) ----
export interface CreditoFactura {
  numero: string;
  fecha: string; // YYYY-MM-DD (vencimiento, o fecha de la factura si no tiene)
  dias: number; // días transcurridos; negativo = plazo aún vigente
  total: number;
  abonado: number;
  saldo: number;
  cuotas: number;
}

export interface CreditoCliente {
  cliente: string;
  documento: string;
  telefono: string;
  facturas: number;
  total: number;
  abonado: number;
  saldo: number;
  dias_mas_vieja: number;
  tramos: Record<string, number>;
  detalle: CreditoFactura[];
}

export interface CarteraResult {
  generado: string;
  desde: string;
  hasta: string;
  saldo: number;
  facturado: number;
  abonado: number;
  clientes: number;
  facturas: number;
  tramos: { etiqueta: string; monto: number }[];
  detalle: CreditoCliente[];
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text.slice(0, 200)}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => fetch("/api/health").then((r) => json<{ ok: boolean }>(r)),

  providers: (refresh = false) =>
    fetch(`/api/providers?refresh=${refresh}`).then((r) => json<Provider[]>(r)),

  searchProducts: (q: string, limit = 30) =>
    fetch(`/api/products?q=${encodeURIComponent(q)}&limit=${limit}`).then((r) =>
      json<Product[]>(r)
    ),

  check: (provider_id: string, items: TirillaItem[]) =>
    fetch("/api/homologacion/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider_id, items }),
    }).then((r) => json<CheckResult>(r)),

  assign: (args: {
    provider_id: string;
    provider_name?: string;
    descripcion: string;
    product_id: string;
    product_name?: string;
    factor?: number;
  }) =>
    fetch("/api/homologacion/assign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) =>
      json<{ ok: boolean; product_id: string; product_name: string }>(r)
    ),

  unassign: (provider_id: string, descripcion: string) =>
    fetch("/api/homologacion/unassign", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider_id, descripcion }),
    }).then((r) => json<{ ok: boolean }>(r)),

  cacheStatus: () => fetch("/api/cache/status").then((r) => json<CacheStatus>(r)),

  cacheRefresh: () =>
    fetch("/api/cache/refresh", { method: "POST" }).then((r) => json<CacheStatus>(r)),

  extraer: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/extraer", { method: "POST", body: fd }).then((r) =>
      json<ExtractResult>(r)
    );
  },

  crearMovimiento: (args: {
    provider_id: string;
    invoice_number?: string;
    fecha?: string | null;
    pagado?: boolean;
    nota?: string;
    items: { descripcion: string; product_id: string; cantidad: number; total: number; factor?: number }[];
  }) =>
    fetch("/api/movimiento", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) => json<MovimientoResult>(r)),

  eliminarMovimiento: (movementId: string) =>
    fetch(`/api/movimiento/${encodeURIComponent(movementId)}`, {
      method: "DELETE",
    }).then((r) => json<{ ok: boolean; movement_id: string }>(r)),

  chat: (args: { mensaje: string; factura?: Extraccion | null; historial?: ChatTurn[] }) =>
    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) => json<ChatResult>(r)),

  // ---- Gastos ----
  gastosTipos: () => fetch("/api/gastos/tipos").then((r) => json<TipoGasto[]>(r)),

  gastosResponsables: () =>
    fetch("/api/gastos/responsables").then((r) => json<Responsable[]>(r)),

  gastosExtraer: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch("/api/gastos/extraer", { method: "POST", body: fd }).then((r) =>
      json<GastoExtractResult>(r)
    );
  },

  gastosChat: (args: { mensaje: string; gasto?: GastoExtraccion | null; historial?: ChatTurn[] }) =>
    fetch("/api/gastos/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) => json<GastoChatResult>(r)),

  crearGasto: (args: {
    type_expense_id: string;
    paid_to_id?: string;
    provider_id?: string;
    invoice_number?: string;
    forma_pago?: string;
    concepto: string;
    subtotal: number;
    impuestos: number;
    sale_de_caja?: boolean;
    fecha?: string | null;
  }) =>
    fetch("/api/gastos", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) => json<CrearGastoResult>(r)),

  // ---- Cartera ----
  creditos: (desde?: string, hasta?: string) => {
    const qs = new URLSearchParams();
    if (desde) qs.set("desde", desde);
    if (hasta) qs.set("hasta", hasta);
    const q = qs.toString();
    return fetch(`/api/creditos${q ? `?${q}` : ""}`).then((r) => json<CarteraResult>(r));
  },

  eliminarGasto: (expenseId: string) =>
    fetch(`/api/gastos/${encodeURIComponent(expenseId)}`, { method: "DELETE" }).then((r) =>
      json<{ ok: boolean; expense_id: string }>(r)
    ),

  // ---- Recurrentes ----
  recurrentes: () =>
    fetch("/api/gastos/recurrentes").then((r) =>
      json<{ items: Recurrente[]; total: number }>(r)
    ),

  guardarRecurrente: (args: Partial<Recurrente> & { nombre: string; type_expense_id: string }) =>
    fetch("/api/gastos/recurrentes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) => json<GuardadoResult>(r)),

  eliminarRecurrente: (id: string) =>
    fetch(`/api/gastos/recurrentes/${encodeURIComponent(id)}`, { method: "DELETE" }).then((r) =>
      json<GuardadoResult>(r)
    ),

  /** Día de pago: un gasto por beneficiario, nunca uno combinado. */
  crearGastosLote: (args: {
    lineas: { recurrente_id: string; monto: number; notas?: string }[];
    fecha?: string | null;
  }) =>
    fetch("/api/gastos/lote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(args),
    }).then((r) => json<LoteResult>(r)),

  // ---- Utilidad ----
  utilidad: (args: { desde?: string; hasta?: string; meses?: number } = {}) => {
    const qs = new URLSearchParams();
    if (args.desde) qs.set("desde", args.desde);
    if (args.hasta) qs.set("hasta", args.hasta);
    if (args.meses) qs.set("meses", String(args.meses));
    const q = qs.toString();
    return fetch(`/api/utilidad${q ? `?${q}` : ""}`).then((r) => json<UtilidadResult>(r));
  },

  sugerenciasRecurrentes: (dias = 180) =>
    fetch(`/api/gastos/recurrentes/sugerencias?dias=${dias}`).then((r) =>
      json<{ desde: string; hasta: string; sugerencias: SugerenciaRecurrente[] }>(r)
    ),
};
