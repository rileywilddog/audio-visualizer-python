import atexit
import os
from os.path import expanduser
from queue import Queue
import signal
import sys
from PyQt5 import uic
from PyQt5.QtGui import QColor, QFont, QPixmap
from PyQt5.QtCore import pyqtSignal, QObject, QSettings, QThread, QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QColorDialog,
    QDesktopWidget,
    QFileDialog,
    QFontDialog,
)

import core
import preview_thread
import video_thread


class Command(QObject):

    videoTask = pyqtSignal(
        str, str, QFont, float, int, int, int, int, int, tuple, tuple, str, str
    )

    def __init__(self):
        QObject.__init__(self)

        import argparse

        self.parser = argparse.ArgumentParser(
            description="Create a visualization for an audio file"
        )
        self.parser.add_argument(
            "-i", "--input", dest="input", help="input audio file", required=True
        )
        self.parser.add_argument(
            "-o", "--output", dest="output", help="output video file", required=True
        )
        self.parser.add_argument(
            "-b",
            "--background",
            dest="bgimage",
            help="background image file",
            required=True,
        )
        self.parser.add_argument(
            "-t", "--text", dest="text", help="title text", required=True
        )
        self.parser.add_argument(
            "-f", "--font", dest="font", help="title font", required=False
        )
        self.parser.add_argument(
            "-r",
            "--resolution",
            dest="resolution",
            help="video resolution (WxH, e.g. 1280x720)",
            required=False,
        )
        self.parser.add_argument(
            "--fps", dest="fps", help="frames per second", required=False
        )
        self.parser.add_argument(
            "-s", "--fontsize", dest="fontsize", help="title font size", required=False
        )
        self.parser.add_argument(
            "-c",
            "--textcolor",
            dest="textcolor",
            help="title text color in r,g,b format",
            required=False,
        )
        self.parser.add_argument(
            "-C",
            "--viscolor",
            dest="viscolor",
            help="visualization color in r,g,b format",
            required=False,
        )
        self.parser.add_argument(
            "-x",
            "--xposition",
            dest="xposition",
            help="text x position",
            required=False,
        )
        self.parser.add_argument(
            "-y",
            "--yposition",
            dest="yposition",
            help="text y position",
            required=False,
        )
        self.parser.add_argument(
            "-a",
            "--alignment",
            dest="alignment",
            help="title alignment",
            required=False,
            type=int,
            choices=[0, 1, 2],
        )
        self.args = self.parser.parse_args()

        self.settings = QSettings("settings.ini", QSettings.IniFormat)

        # load colours as tuples from comma-separated strings
        self.textColor = core.Core.RGBFromString(
            self.settings.value("textColor", "255, 255, 255")
        )
        self.visColor = core.Core.RGBFromString(
            self.settings.value("visColor", "255, 255, 255")
        )
        if self.args.textcolor:
            self.textColor = core.Core.RGBFromString(self.args.textcolor)
        if self.args.viscolor:
            self.visColor = core.Core.RGBFromString(self.args.viscolor)

        # font settings
        if self.args.font:
            self.font = QFont(self.args.font, self.fontsize)
        else:
            self.font = QFont()
            self.font.fromString(self.settings.value("titleFont"))
        if self.args.fontsize:
            self.font.setPointSize(self.fontsize)

        if self.args.alignment:
            self.alignment = int(self.args.alignment)
        else:
            self.alignment = int(self.settings.value("alignment", 0))

        if self.args.fps:
            self.fps = float(self.args.fps)
        else:
            self.fps = float(self.settings.value("fps", 30))

        if self.args.resolution:
            x, y = self.args.resolution.split("x")
            self.resX = int(x)
            self.resY = int(y)
        else:
            self.resX = int(self.settings.value("xResolution", 1280))
            self.resY = int(self.settings.value("yResolution", 720))

        if self.args.xposition:
            self.textX = int(self.args.xposition)
        else:
            self.textX = int(self.settings.value("xPosition", 0))

        if self.args.yposition:
            self.textY = int(self.args.yposition)
        else:
            self.textY = int(self.settings.value("yPosition", 0))

        self.videoThread = QThread(self)
        self.videoWorker = video_thread.Worker(self)

        self.videoWorker.moveToThread(self.videoThread)
        self.videoWorker.videoCreated.connect(self.videoCreated)

        self.videoThread.start()
        self.videoTask.emit(
            self.args.bgimage,
            self.args.text,
            self.font,
            self.fps,
            self.alignment,
            self.textX,
            self.textY,
            self.resX,
            self.resY,
            self.textColor,
            self.visColor,
            self.args.input,
            self.args.output,
        )

    def videoCreated(self):
        self.videoThread.quit()
        self.videoThread.wait()
        self.cleanUp()

    def cleanUp(self):
        self.settings.setValue("titleFont", self.font.toString())
        self.settings.setValue("fps", str(self.fps))
        self.settings.setValue("alignment", str(self.alignment))
        self.settings.setValue("xPosition", str(self.textX))
        self.settings.setValue("yPosition", str(self.textY))
        self.settings.setValue("xResolution", str(self.resX))
        self.settings.setValue("yResolution", str(self.resY))
        self.settings.setValue("visColor", "%s,%s,%s" % self.visColor)
        self.settings.setValue("textColor", "%s,%s,%s" % self.textColor)
        sys.exit(0)


class Main(QObject):

    previewTask = pyqtSignal(
        str, str, QFont, int, int, int, int, int, tuple, tuple, int, int
    )
    processTask = pyqtSignal()
    videoTask = pyqtSignal(
        str, str, QFont, float, int, int, int, int, int, tuple, tuple, str, str
    )

    def __init__(self, window):
        QObject.__init__(self)

        # print('main thread id: {}'.format(QThread.currentThreadId()))
        self.window = window
        self.core = core.Core()
        self.settings = QSettings("settings.ini", QSettings.IniFormat)

        # load colors as tuples from a comma-separated string
        self.textColor = core.Core.RGBFromString(
            self.settings.value("textColor", "255, 255, 255")
        )
        self.visColor = core.Core.RGBFromString(
            self.settings.value("visColor", "255, 255, 255")
        )

        self.previewQueue = Queue()

        self.previewThread = QThread(self)
        self.previewWorker = preview_thread.Worker(self, self.previewQueue)

        self.previewWorker.moveToThread(self.previewThread)
        self.previewWorker.imageCreated.connect(self.showPreviewImage)

        self.previewThread.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.processTask.emit)
        self.timer.start(500)

        window.pushButton_font.clicked.connect(self.openFontDialog)
        window.pushButton_selectInput.clicked.connect(self.openInputFileDialog)
        window.pushButton_selectOutput.clicked.connect(self.openOutputFileDialog)
        window.pushButton_createVideo.clicked.connect(self.createAudioVisualisation)
        window.pushButton_selectBackground.clicked.connect(
            self.openBackgroundFileDialog
        )

        window.progressBar_create.setValue(0)
        window.setWindowTitle("Audio Visualizer")
        window.pushButton_selectInput.setText("Input Audio")
        window.pushButton_selectOutput.setText("Output Video")
        window.pushButton_selectBackground.setText("Background")
        window.pushButton_font.setText("Font")
        window.label_alignment.setText("Title Options")
        window.label_visOptions.setText("Visualization")
        window.label_title.setText("Title Text")
        window.label_video_settings.setText("Video Settings")
        window.label_video_res_x.setText("H. Res")
        window.label_video_res_y.setText("V. Res")
        window.label_video_fps.setText("FPS")
        window.pushButton_createVideo.setText("Create Video")
        window.groupBox_create.setTitle("Create")
        window.groupBox_settings.setTitle("Settings")
        window.groupBox_preview.setTitle("Preview")

        window.lineEdit_video_res_x.setText(str(1280))
        window.lineEdit_video_res_y.setText(str(720))
        window.comboBox_video_fps.addItems(["29.97", "30", "59.94", "60"])
        window.alignmentComboBox.addItems(["Left", "Center", "Right"])
        window.textXSpinBox.setValue(0)
        window.textYSpinBox.setValue(0)
        window.pushButton_textColor.clicked.connect(lambda: self.pickColor("text"))
        window.pushButton_visColor.clicked.connect(lambda: self.pickColor("vis"))
        window.comboBox_visStyle.addItems(["Mirrored", "Up", "Down", "Circle"])
        btnStyle = (
            "QPushButton { background-color : %s; outline: none; }"
            % QColor(*self.textColor).name()
        )
        window.pushButton_textColor.setStyleSheet(btnStyle)
        btnStyle = (
            "QPushButton { background-color : %s; outline: none; }"
            % QColor(*self.visColor).name()
        )
        window.pushButton_visColor.setStyleSheet(btnStyle)

        input_file = self.settings.value("input")
        if input_file is not None:
            self.window.label_input.setText(input_file)
        background_file = self.settings.value("background")
        if background_file is not None:
            self.window.label_background.setText(background_file)

        fps = self.settings.value("fps")
        if fps is not None:
            window.comboBox_video_fps.setCurrentText(fps)
        alignment = self.settings.value("alignment")
        if alignment is not None:
            window.alignmentComboBox.setCurrentIndex(int(alignment))
        xPosition = self.settings.value("xPosition")
        if xPosition is not None:
            window.textXSpinBox.setValue(int(xPosition))
        yPosition = self.settings.value("yPosition")
        if yPosition is not None:
            window.textYSpinBox.setValue(int(yPosition))
        xResolution = self.settings.value("xResolution")
        if xResolution is not None:
            window.lineEdit_video_res_x.setText(xResolution)
        yResolution = self.settings.value("yResolution")
        if yResolution is not None:
            window.lineEdit_video_res_y.setText(yResolution)
        title = self.settings.value("title")
        if title is not None:
            self.window.lineEdit_title.setText(title)

        window.lineEdit_title.textChanged.connect(self.drawPreview)
        window.alignmentComboBox.currentIndexChanged.connect(self.drawPreview)
        window.textXSpinBox.valueChanged.connect(self.drawPreview)
        window.textYSpinBox.valueChanged.connect(self.drawPreview)
        window.comboBox_visStyle.currentIndexChanged.connect(self.drawPreview)
        window.lineEdit_video_res_x.textChanged.connect(self.drawPreview)
        window.lineEdit_video_res_y.textChanged.connect(self.drawPreview)

        window.show()
        self.drawPreview()

    def cleanUp(self):
        self.timer.stop()
        self.previewThread.quit()
        self.previewThread.wait()

        self.settings.setValue("input", self.window.label_input.text())
        self.settings.setValue("background", self.window.label_background.text())
        self.settings.setValue("fps", str(self.window.comboBox_video_fps.currentText()))
        self.settings.setValue(
            "alignment", str(self.window.alignmentComboBox.currentIndex())
        )
        self.settings.setValue("xPosition", str(self.window.textXSpinBox.value()))
        self.settings.setValue("yPosition", str(self.window.textYSpinBox.value()))
        self.settings.setValue(
            "xResolution", str(self.window.lineEdit_video_res_x.text())
        )
        self.settings.setValue(
            "yResolution", str(self.window.lineEdit_video_res_y.text())
        )
        self.settings.setValue("title", self.window.lineEdit_title.text())

    def openFontDialog(self):
        current_font = QFont()
        current_font.fromString(self.settings.value("titleFont"))
        fontdata, ok = QFontDialog.getFont(current_font)
        self.settings.setValue("titleFont", fontdata.toString())
        self.drawPreview()

    def openInputFileDialog(self):
        inputDir = self.settings.value("inputDir", expanduser("~"))

        fileName = QFileDialog.getOpenFileName(
            self.window,
            "Open Music File",
            inputDir,
            "Music Files (*.mp3 *.wav *.ogg *.flac)",
        )[0]

        if not fileName == "":
            self.settings.setValue("inputDir", os.path.dirname(fileName))
            self.window.label_input.setText(fileName)

    def openOutputFileDialog(self):
        outputDir = self.settings.value("outputDir", expanduser("~"))

        fileName = QFileDialog.getSaveFileName(
            self.window,
            "Set Output Video File",
            outputDir,
            "Video Files (*.mp4 *.mkv *.mov)",
        )[0]

        if not fileName == "":
            self.settings.setValue("outputDir", os.path.dirname(fileName))
            self.window.label_output.setText(fileName)

    def openBackgroundFileDialog(self):
        backgroundDir = self.settings.value("backgroundDir", expanduser("~"))

        fileName = QFileDialog.getOpenFileName(
            self.window,
            "Open Background Image",
            backgroundDir,
            "Image Files (*.jpg *.jpeg *.png *.webp);; Video Files (*.mp4 *.mkv *.webm)",
        )[0]

        if not fileName == "":
            self.settings.setValue("backgroundDir", os.path.dirname(fileName))
            self.window.label_background.setText(fileName)
        self.drawPreview()

    def createAudioVisualisation(self):
        if self.window.label_input.text() == "":
            self.progressBarSetText("Error: No input")
            return
        if self.window.label_output.text() == "":
            self.progressBarSetText("Error: No output")
            return
        if self.window.label_background.text() == "":
            self.progressBarSetText("Error: No background")
            return

        self.videoThread = QThread(self)
        self.videoWorker = video_thread.Worker(self)

        self.videoWorker.moveToThread(self.videoThread)
        self.videoWorker.videoCreated.connect(self.videoCreated)
        self.videoWorker.progressBarUpdate.connect(self.progressBarUpdated)
        self.videoWorker.progressBarSetText.connect(self.progressBarSetText)

        current_font = QFont()
        current_font.fromString(self.settings.value("titleFont"))

        self.videoThread.start()
        self.videoTask.emit(
            self.window.label_background.text(),
            self.window.lineEdit_title.text(),
            current_font,
            float(self.window.comboBox_video_fps.currentText()),
            self.window.alignmentComboBox.currentIndex(),
            self.window.textXSpinBox.value(),
            self.window.textYSpinBox.value(),
            int(self.window.lineEdit_video_res_x.text()),
            int(self.window.lineEdit_video_res_y.text()),
            core.Core.RGBFromString(self.settings.value("textColor")),
            core.Core.RGBFromString(self.settings.value("visColor")),
            self.window.label_input.text(),
            self.window.label_output.text(),
        )

    def progressBarUpdated(self, value):
        self.window.progressBar_create.setValue(value)

    def progressBarSetText(self, value):
        self.window.progressBar_create.setFormat(value)

    def videoCreated(self):
        self.videoThread.quit()
        self.videoThread.wait()

    def drawPreview(self):
        if (
            not self.window.lineEdit_video_res_x.text().isnumeric()
            or not self.window.lineEdit_video_res_y.text().isnumeric()
        ):
            return

        current_font = QFont()
        current_font.fromString(self.settings.value("titleFont"))

        self.previewTask.emit(
            self.window.label_background.text(),
            self.window.lineEdit_title.text(),
            current_font,
            self.window.alignmentComboBox.currentIndex(),
            self.window.textXSpinBox.value(),
            self.window.textYSpinBox.value(),
            int(self.window.lineEdit_video_res_x.text()),
            int(self.window.lineEdit_video_res_y.text()),
            core.Core.RGBFromString(self.settings.value("textColor")),
            core.Core.RGBFromString(self.settings.value("visColor")),
            self.window.label_preview.width(),
            self.window.label_preview.height(),
        )
        # self.processTask.emit()

    def showPreviewImage(self, image):
        self._scaledPreviewImage = image
        self._previewPixmap = QPixmap.fromImage(self._scaledPreviewImage)

        self.window.label_preview.setPixmap(self._previewPixmap)

    def pickColor(self, colorTarget):
        # This is gross, but the other option is rewriting all the settings stuff
        current_color = QColor(
            *[int(x) for x in self.settings.value(colorTarget + "Color").split(",")]
        )
        color = QColorDialog.getColor(current_color)
        if color.isValid():
            RGBstring = "%s,%s,%s" % (
                str(color.red()),
                str(color.green()),
                str(color.blue()),
            )
            btnStyle = (
                "QPushButton { background-color : %s; outline: none; }" % color.name()
            )
            if colorTarget == "text":
                window.pushButton_textColor.setStyleSheet(btnStyle)
            elif colorTarget == "vis":
                window.pushButton_visColor.setStyleSheet(btnStyle)
            self.settings.setValue(colorTarget + "Color", RGBstring)
            self.drawPreview()


if len(sys.argv) > 1:
    # command line mode
    app = QApplication(sys.argv + ["-platform", "offscreen"])
    command = Command()
    signal.signal(signal.SIGINT, command.cleanUp)
    sys.exit(app.exec_())
else:
    # gui mode
    if __name__ == "__main__":
        app = QApplication(sys.argv)
        window = uic.loadUi("main.ui")
        # window.adjustSize()
        desc = QDesktopWidget()
        dpi = desc.physicalDpiX()
        topMargin = 0 if (dpi == 96) else int(10 * (dpi / 96))

        window.resize(
            int(window.width() * (dpi / 96)), int(window.height() * (dpi / 96))
        )
        window.verticalLayout_2.setContentsMargins(0, topMargin, 0, 0)

        main = Main(window)

        signal.signal(signal.SIGINT, main.cleanUp)
        atexit.register(main.cleanUp)

        sys.exit(app.exec_())
