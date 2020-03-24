from PyQt5.QtCore import pyqtSignal, pyqtSlot, QObject, Qt
from PyQt5.QtGui import QFont, QImage
from PIL.ImageQt import ImageQt
import core
from queue import Empty
import numpy


class Worker(QObject):

    imageCreated = pyqtSignal(["QImage"])

    def __init__(self, parent=None, queue=None):
        QObject.__init__(self)
        parent.previewTask.connect(self.createPreviewImage)
        parent.processTask.connect(self.process)
        self.core = core.Core()
        self.queue = queue

    @pyqtSlot(str, str, QFont, int, int, int, int, int, tuple, tuple, int, int)
    def createPreviewImage(
        self,
        backgroundImage,
        titleText,
        titleFont,
        alignment,
        xOffset,
        yOffset,
        xResolution,
        yResolution,
        textColor,
        visColor,
        previewXResolution,
        previewYResolution,
    ):
        # print('worker thread id: {}'.format(QThread.currentThreadId()))
        dic = {
            "backgroundImage": backgroundImage,
            "titleText": titleText,
            "titleFont": titleFont,
            "alignment": alignment,
            "xoffset": xOffset,
            "yoffset": yOffset,
            "xResolution": xResolution,
            "yResolution": yResolution,
            "textColor": textColor,
            "visColor": visColor,
            "previewXResolution": previewXResolution,
            "previewYResolution": previewYResolution,
        }
        self.queue.put(dic)

    @pyqtSlot()
    def process(self):
        try:
            nextPreviewInformation = self.queue.get(block=False)
            while self.queue.qsize() >= 2:
                try:
                    self.queue.get(block=False)
                except Empty:
                    continue

            bgImage = self.core.parseBaseImage(
                nextPreviewInformation["backgroundImage"], preview=True
            )
            if bgImage == []:
                bgImage = ""
            else:
                bgImage = bgImage[0]

            im = self.core.drawBaseImage(
                bgImage,
                nextPreviewInformation["titleText"],
                nextPreviewInformation["titleFont"],
                nextPreviewInformation["alignment"],
                nextPreviewInformation["xoffset"],
                nextPreviewInformation["yoffset"],
                nextPreviewInformation["xResolution"],
                nextPreviewInformation["yResolution"],
                nextPreviewInformation["textColor"],
                nextPreviewInformation["visColor"],
            )
            spectrum = numpy.fromfunction(
                lambda x: 0.008 * (x - 128) ** 2, (255,), dtype="int16"
            )

            im = self.core.drawBars(
                spectrum,
                im,
                nextPreviewInformation["visColor"],
                nextPreviewInformation["xResolution"],
                nextPreviewInformation["yResolution"],
            )

            self._image = ImageQt(im)
            self._previewImage = QImage(self._image)

            self._scaledPreviewImage = self._previewImage.scaled(
                nextPreviewInformation["previewXResolution"],
                nextPreviewInformation["previewYResolution"],
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )

            self.imageCreated.emit(self._scaledPreviewImage)
        except Empty:
            True
