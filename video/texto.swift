// Renderiza texto a PNG con tipografia real, via CoreText.
//
// Existe porque el ffmpeg de esta maquina no trae drawtext (sin freetype), y
// un texto dibujado con fuente de mapa de bits se ve casero. CoreText da
// antialias y kerning de verdad, que es lo que separa una visualizacion
// cientifica presentable de una que parece una captura.
//
// uso: texto "cadena" tamaño r g b salida.png [peso]
import Foundation
import CoreGraphics
import CoreText

let a = CommandLine.arguments
guard a.count >= 7 else {
    FileHandle.standardError.write("uso: texto <cadena> <tamaño> <r> <g> <b> <salida.png> [peso]\n".data(using: .utf8)!)
    exit(1)
}
let cadena = a[1]
let tam = CGFloat(Double(a[2]) ?? 48)
let color = CGColor(red: CGFloat(Double(a[3])! / 255), green: CGFloat(Double(a[4])! / 255),
                    blue: CGFloat(Double(a[5])! / 255), alpha: 1)
let salida = a[6]
let peso: CGFloat = a.count > 7 ? CGFloat(Double(a[7]) ?? 0) : 0.2

let fuente = CTFontCreateUIFontForLanguage(.system, tam, nil)
    ?? CTFontCreateWithName("Helvetica" as CFString, tam, nil)
// Claves de CoreText directamente: las de NSAttributedString.Key necesitan
// AppKit, que aqui no hace falta arrastrar.
let atributos: [CFString: Any] = [
    kCTFontAttributeName: fuente,
    kCTForegroundColorAttributeName: color,
    // El tracking ligero hace que los titulos respiren; sin el se ven apretados.
    kCTKernAttributeName: tam * 0.02,
]
let attr = CFAttributedStringCreate(nil, cadena as CFString, atributos as CFDictionary)!
let linea = CTLineCreateWithAttributedString(attr)
let limites = CTLineGetBoundsWithOptions(linea, .useOpticalBounds)

let margen: CGFloat = tam * 0.3
let ancho = Int(ceil(limites.width + margen * 2))
let alto = Int(ceil(limites.height + margen * 2))

guard let ctx = CGContext(data: nil, width: ancho, height: alto, bitsPerComponent: 8,
                          bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                          bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else {
    exit(2)
}
ctx.setAllowsAntialiasing(true)
ctx.setShouldSmoothFonts(true)
ctx.textPosition = CGPoint(x: margen - limites.origin.x, y: margen - limites.origin.y)
CTLineDraw(linea, ctx)

// Se escribe RGBA crudo, no PNG: quien lo consume es un script de Node que no
// tiene decodificador de PNG, y guardar los bytes tal cual evita arrastrar una
// dependencia solo para volver a descomprimirlos.
guard let datos = ctx.data else { exit(3) }
let bytes = ctx.bytesPerRow * alto
let d = Data(bytes: datos, count: bytes)
try? d.write(to: URL(fileURLWithPath: salida))
// El consumidor necesita bytesPerRow: CoreGraphics alinea las filas y no
// siempre vale ancho*4.
print("\(ancho) \(alto) \(ctx.bytesPerRow)")
