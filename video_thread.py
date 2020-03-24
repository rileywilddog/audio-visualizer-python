from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject
from PyQt5.QtGui import QFont
import core
import numpy
import subprocess
import sys


class Worker(QObject):

    videoCreated = pyqtSignal()
    progressBarUpdate = pyqtSignal(int)
    progressBarSetText = pyqtSignal(str)

    def __init__(self, parent=None):
        QObject.__init__(self)
        parent.videoTask.connect(self.createVideo)
        self.core = core.Core()

    @pyqtSlot(str, str, QFont, float, int, int, int, int, int, tuple, tuple, str, str)
    def createVideo(
        self,
        backgroundImage,
        titleText,
        titleFont,
        fps,
        alignment,
        xOffset,
        yOffset,
        xResolution,
        yResolution,
        textColor,
        visColor,
        inputFile,
        outputFile,
    ):
        import cProfile

        with cProfile.Profile() as pr:
            # print('worker thread id: {}'.format(QThread.currentThreadId()))
            def getBackgroundAtIndex(i):
                return self.core.drawBaseImage(
                    backgroundFrames[i],
                    titleText,
                    titleFont,
                    alignment,
                    xOffset,
                    yOffset,
                    xResolution,
                    yResolution,
                    textColor,
                    visColor,
                )

            progressBarValue = 0
            self.progressBarUpdate.emit(progressBarValue)
            self.progressBarSetText.emit("Loading background image…")

            backgroundFrames = self.core.parseBaseImage(backgroundImage)
            if len(backgroundFrames) < 2:
                # the base image is not a video so we can draw it now
                imBackground = getBackgroundAtIndex(0)
            else:
                # base images will be drawn while drawing the audio bars
                imBackground = None

            self.progressBarSetText.emit("Loading audio file…")
            completeAudioArray = self.core.readAudioFile(inputFile)

            acodec = "aac"  # TODO argument
            if acodec == "aac":
                # test if user has libfdk_aac
                encoders = subprocess.check_output(
                    self.core.FFMPEG_BIN + " -encoders -hide_banner", shell=True
                )
                if b"libfdk_aac" in encoders:
                    acodec = "libfdk_aac"
                else:
                    acodec = "aac"
            if not acodec.startswith("pcm"):
                abitrate = ["-b:a", "192k"]
            else:
                abitrate = []

            ffmpegCommand = [self.core.FFMPEG_BIN, "-hide_banner"]
            ffmpegCommand += ["-f", "rawvideo"]
            ffmpegCommand += ["-vcodec", "rawvideo"]
            ffmpegCommand += ["-s", "{}x{}".format(xResolution, yResolution)]
            ffmpegCommand += ["-pix_fmt", "rgb24"]
            ffmpegCommand += ["-r", str(fps)]  # framerate
            ffmpegCommand += ["-i", "-"]  # video in from a pipe
            ffmpegCommand += ["-i", inputFile]  # audio in file
            ffmpegCommand += ["-acodec", acodec]  # output audio codec
            ffmpegCommand += abitrate
            ffmpegCommand += ["-vcodec", "libx264"]
            ffmpegCommand += ["-pix_fmt", "yuv420p"]
            ffmpegCommand += ["-preset", "medium"]
            ffmpegCommand += ["-crf", str(20)]
            ffmpegCommand += ["-y", outputFile]  # overwrite (qt already confirmed)

            if acodec == "aac" and outputFile.endswith(".mp4"):
                ffmpegCommand += ["-strict", "-2"]

            out_pipe = subprocess.Popen(
                ffmpegCommand,
                stdin=subprocess.PIPE,
                stdout=sys.stdout,
                stderr=sys.stdout,
            )

            smoothConstantDown = 0.08
            smoothConstantUp = 0.8
            lastSpectrum = None
            sampleSize = 1470

            numpy.seterr(divide="ignore")
            bgI = 0
            for i in range(0, len(completeAudioArray), sampleSize):
                # create video for output
                lastSpectrum = self.core.transformData(
                    i,
                    completeAudioArray,
                    sampleSize,
                    smoothConstantDown,
                    smoothConstantUp,
                    lastSpectrum,
                )
                if imBackground is not None:
                    im = self.core.drawBars(
                        lastSpectrum, imBackground, visColor, xResolution, yResolution
                    )
                else:
                    im = self.core.drawBars(
                        lastSpectrum,
                        getBackgroundAtIndex(bgI),
                        visColor,
                        xResolution,
                        yResolution,
                    )
                    if bgI < len(backgroundFrames) - 1:
                        bgI += 1

                # write to out_pipe
                try:
                    out_pipe.stdin.write(im.tobytes())
                finally:
                    True

                # increase progress bar value
                if progressBarValue + 1 <= (i / len(completeAudioArray)) * 100:
                    progressBarValue = numpy.floor((i / len(completeAudioArray)) * 100)
                    self.progressBarUpdate.emit(progressBarValue)
                    self.progressBarSetText.emit("%s%%" % str(int(progressBarValue)))

            numpy.seterr(all="print")

            out_pipe.stdin.close()
            if out_pipe.stderr is not None:
                print(out_pipe.stderr.read())
                out_pipe.stderr.close()
            # out_pipe.terminate() # don't terminate ffmpeg too early
            out_pipe.wait()
            print("Video file created")
            self.core.deleteTempDir()
            self.progressBarUpdate.emit(100)
            self.progressBarSetText.emit("100%")
            self.videoCreated.emit()
        pr.dump_stats("profile.bin")
