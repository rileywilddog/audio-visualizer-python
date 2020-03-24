import atexit
import errno
import io
import numpy
import os
from PIL import Image, ImageDraw
from PIL.ImageQt import ImageQt
from PyQt5.QtCore import QBuffer, QIODevice
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QImage
from shutil import rmtree
import subprocess
import sys
import tempfile


class Core:
    def __init__(self):
        self.lastBackgroundImage = ""
        self.lastBackgroundResolution = (0, 0)
        self._image = None

        self.FFMPEG_BIN = self.findFfmpeg()
        self.tempDir = None
        atexit.register(self.deleteTempDir)

    def findFfmpeg(self):
        if sys.platform == "win32":
            return "ffmpeg.exe"
        else:
            try:
                subprocess.check_call(
                    ["ffmpeg", "-version"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return "ffmpeg"
            except OSError as e:
                if e.errno == errno.ENOENT:
                    return "avconv"
                else:
                    raise

    def parseBaseImage(self, backgroundImage, preview=False):
        """ determines if the base image is a single frame or list of frames """
        if backgroundImage == "":
            return []
        else:
            _, bgExt = os.path.splitext(backgroundImage)
            if bgExt not in [".mp4", ".mkv"]:
                return [backgroundImage]
            else:
                return self.getVideoFrames(backgroundImage, preview)

    def drawBaseImage(
        self,
        backgroundFile,
        titleText,
        titleFont,
        alignment,
        xOffset,
        yOffset,
        xResolution,
        yResolution,
        textColor,
        visColor,
    ):
        if backgroundFile == "":
            im = Image.new("RGB", (xResolution, yResolution), "black")
        else:
            im = Image.open(backgroundFile)

        if (
            self._image is None
            or not self.lastBackgroundImage == backgroundFile
            or not self.lastBackgroundResolution == (xResolution, yResolution)
        ):
            self.lastBackgroundResolution = (xResolution, yResolution)
            self.lastBackgroundImage = backgroundFile

            # resize if necessary
            if not im.size == (xResolution, yResolution):
                im = im.resize((xResolution, yResolution), Image.ANTIALIAS)

            self._image = ImageQt(im)

        self._image1 = QImage(self._image)
        painter = QPainter(self._image1)
        font = titleFont
        painter.setFont(font)
        painter.setPen(QColor(*textColor))

        fm = QFontMetrics(font)
        # X
        if alignment == 0:  # Left
            xPosition = xOffset + 20
        if alignment == 1:  # Center
            xPosition = xResolution / 2 - fm.width(titleText) / 2 + xOffset
        if alignment == 2:  # Right
            xPosition = xResolution - fm.width(titleText) - xOffset - 20
        # Y
        yPosition = yResolution / 2 + fm.height() / 2 - yOffset
        # Draw
        painter.drawText(xPosition, yPosition, titleText)
        painter.end()

        buffer = QBuffer()
        buffer.open(QIODevice.ReadWrite)
        self._image1.save(buffer, "PNG")

        strio = io.BytesIO()
        strio.write(buffer.data())
        buffer.close()
        strio.seek(0)
        return Image.open(strio)

    def drawBars(
        self,
        spectrum,
        image,
        color,
        xResolution,
        yResolution,
        count=63,
        mult=4,
        width=10,
        gap=10,
        border=5,
        border_opacity=50,
        margin=15,
        baseline_spread=40,
    ):
        im = image.copy()
        draw = ImageDraw.Draw(im, "RGBA")
        border_color = color + (border_opacity,)

        for d in (1, -1):  # Top and bottom mirror
            baseline = yResolution / 2 - d * baseline_spread
            for j in range(count):
                # (x0, y0, x1, y1)
                # border
                if border_opacity > 0:
                    draw.rectangle(
                        (
                            margin + j * (width + gap) - border,
                            baseline + d * border,
                            margin + j * (width + gap) + width - 1 + border,
                            baseline - d * (spectrum[j * mult] + border),
                        ),
                        fill=border_color,
                    )
                # main
                draw.rectangle(
                    (
                        margin + j * (width + gap),
                        baseline,
                        margin + j * (width + gap) + width - 1,
                        baseline - d * spectrum[j * mult],
                    ),
                    fill=color,
                )

        return im

    def readAudioFile(self, filename):
        rate = 44100
        command = [self.FFMPEG_BIN]
        command += ["-i", filename]
        command += ["-f", "s16le"]
        command += ["-acodec", "pcm_s16le"]
        command += ["-ar", str(rate)]
        command += ["-ac", "1"]  # mono
        command += ["-"]  # to stdout
        in_pipe = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10 ** 8
        )

        completeAudioArray = numpy.empty(0, dtype="int16")

        while True:
            # read 4 seconds of audio (samplerate * 2 bytes * 4 sec)
            raw_audio = in_pipe.stdout.read(rate * 2 * 4)
            if len(raw_audio) == 0:
                break
            audio_array = numpy.fromstring(raw_audio, dtype="int16")
            completeAudioArray = numpy.append(completeAudioArray, audio_array)
            # print(audio_array)

        in_pipe.kill()
        in_pipe.wait()

        # add 0s the end
        completeAudioArrayCopy = numpy.zeros(
            len(completeAudioArray) + rate, dtype="int16"
        )
        completeAudioArrayCopy[: len(completeAudioArray)] = completeAudioArray
        completeAudioArray = completeAudioArrayCopy

        return completeAudioArray

    def transformData(
        self,
        i,
        completeAudioArray,
        sampleSize,
        smoothConstantDown,
        smoothConstantUp,
        lastSpectrum,
    ):
        if len(completeAudioArray) < (i + sampleSize):
            sampleSize = len(completeAudioArray) - i

        window = numpy.hanning(sampleSize)
        data = completeAudioArray[i : i + sampleSize][::1] * window
        paddedSampleSize = 2048
        paddedData = numpy.pad(data, (0, paddedSampleSize - sampleSize), "constant")
        spectrum = numpy.fft.fft(paddedData)
        # sample_rate = 44100
        # frequencies = numpy.fft.fftfreq(len(spectrum), 1.0 / sample_rate)

        y = abs(spectrum[0 : int(paddedSampleSize / 2) - 1])

        # filter the noise away
        # y[y<80] = 0

        y = 20 * numpy.log10(y)
        y[numpy.isinf(y)] = 0

        if lastSpectrum is not None:
            lastSpectrum[y < lastSpectrum] = y[
                y < lastSpectrum
            ] * smoothConstantDown + lastSpectrum[y < lastSpectrum] * (
                1 - smoothConstantDown
            )
            lastSpectrum[y >= lastSpectrum] = y[
                y >= lastSpectrum
            ] * smoothConstantUp + lastSpectrum[y >= lastSpectrum] * (
                1 - smoothConstantUp
            )
        else:
            lastSpectrum = y

        # x = frequencies[0 : int(paddedSampleSize / 2) - 1]

        return lastSpectrum

    def deleteTempDir(self):
        if self.tempDir and os.path.exists(self.tempDir):
            rmtree(self.tempDir)

    def getVideoFrames(self, videoPath, firstOnly=False):
        self.tempDir = os.path.join(
            tempfile.gettempdir(), "audio-visualizer-python-data"
        )
        # recreate the temporary directory so it is empty
        self.deleteTempDir()
        os.mkdir(self.tempDir)
        if firstOnly:
            filename = "preview%s.jpg" % os.path.basename(videoPath).split(".", 1)[0]
            options = "-ss 10 -vframes 1"
        else:
            filename = "$frame%05d.jpg"
            options = ""
        subprocess.call(
            '%s -i "%s" -y %s "%s"'
            % (
                self.FFMPEG_BIN,
                videoPath,
                options,
                os.path.join(self.tempDir, filename),
            ),
            shell=True,
        )
        return sorted([os.path.join(self.tempDir, f) for f in os.listdir(self.tempDir)])

    @staticmethod
    def RGBFromString(string):
        """ turns an RGB string like "255, 255, 255" into a tuple """
        try:
            tup = tuple([int(i) for i in string.split(",")])
            if len(tup) != 3:
                raise ValueError
            for i in tup:
                if i > 255 or i < 0:
                    raise ValueError
            return tup
        except Exception:
            return (255, 255, 255)
