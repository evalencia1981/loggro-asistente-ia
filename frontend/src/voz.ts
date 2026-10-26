// Utilidades del dictado por voz (Web Speech API), compartidas por los chats.

const norm = (s: string) => s.toLowerCase().replace(/\s+/g, " ").trim();

/**
 * Une los resultados de un SpeechRecognition en un solo texto.
 *
 * En escritorio cada resultado es un tramo NUEVO de la frase, así que basta con
 * concatenarlos. Chrome en Android, con `continuous = true`, entrega en cambio
 * cada resultado con la frase ACUMULADA ("pago", "pago nómina", "pago nómina
 * Juan"…); concatenarlos daba "pagopago nóminapago nómina Juan…". Si un
 * resultado empieza con lo ya armado, lo reemplaza en vez de sumarse, y si es
 * un repetido exacto del final, se descarta.
 */
export function unirResultados(results: ArrayLike<ArrayLike<{ transcript: string }>>): string {
  let texto = "";
  for (let i = 0; i < results.length; i++) {
    const t = (results[i][0]?.transcript ?? "").trim();
    if (!t) continue;
    if (!texto || norm(t).startsWith(norm(texto))) texto = t;
    else if (!norm(texto).endsWith(norm(t))) texto = `${texto} ${t}`;
  }
  return texto;
}
