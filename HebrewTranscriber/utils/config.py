from PyQt6.QtCore import QSettings

class Config:
    """Persistent settings manager."""

    def __init__(self):
        self.settings = QSettings('HebrewTranscriber', 'Settings')

    @property
    def last_output_dir(self) -> str:
        return self.settings.value('last_output_dir', '')

    @last_output_dir.setter
    def last_output_dir(self, value: str):
        self.settings.setValue('last_output_dir', value)

    @property
    def output_format(self) -> str:
        return self.settings.value('output_format', 'md')

    @output_format.setter
    def output_format(self, value: str):
        self.settings.setValue('output_format', value)
