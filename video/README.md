# El vídeo, generado por código

45 s a 1920×1080. **No es una grabación de pantalla:** cada cuadro se compone
aquí y se codifica con ffmpeg.

```sh
node video/pelicula.mjs | ffmpeg -f rawvideo -pix_fmt rgb24 -s 1920x1080 -r 30 \
  -i - -c:v h264_videotoolbox -b:v 12M -pix_fmt yuv420p video/wind-pinn.mp4
```

| Fichero | Qué hace |
|---|---|
| `modelo.mjs` | Reimplementa la PINN exportada. Sin dependencias: son pesos crudos |
| `verificar.mjs` | Comprueba que esa reimplementación reproduce la métrica del informe |
| `render.mjs` | Lienzo, escalas de color, partículas, geometría de la ciudad |
| `pelicula.mjs` | Las seis escenas y el bucle principal |
| `texto.swift` | Rótulos con tipografía real, vía CoreText |

## Por qué hay un renderizador de texto en Swift

El ffmpeg de esta máquina no trae `drawtext` (compilado sin freetype), y un
texto dibujado con fuente de mapa de bits se ve casero. CoreText da antialias y
kerning de verdad. Se compila con `swiftc -O -o video/texto video/texto.swift`.

## Dos cosas que costaron

**La entrada del modelo.** Las coordenadas crudas *se conservan* además de los
senos y cosenos de Fourier — por eso la primera capa espera 98 entradas y no 96
— y el ángulo lleva π, no 2π. `verificar.mjs` existe precisamente para no
volver a equivocarse en silencio: si reproduce 0.317, la implementación es
correcta.

**La contrapresión de la tubería.** Escribir 1350 cuadros sin esperar a que
ffmpeg consuma hace que Node los acumule en memoria (8 GB) y la escritura falle
con `EINVAL`. Y el buffer hay que copiarlo antes de enviarlo, porque se
reutiliza en el cuadro siguiente.

## Lo que el vídeo dice

Enseña los números completos, **incluido dónde la PINN pierde**: gana en
velocidad frente a la interpolación y al MLP, y pierde en presión frente a la
interpolación simple. Una demo que sólo enseñe dónde gana no es defendible, y
la explicación física de por qué pierde la hace más convincente, no menos.
