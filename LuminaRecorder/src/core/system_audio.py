"""
Lumina Recorder - Capture du son système (loopback WASAPI)

Enregistre ce que jouent les haut-parleurs (vidéo, musique, notifications)
en plus — ou à la place — du microphone. Utile pour les tutoriels où l'on
veut à la fois sa voix et le son des applications.

Nécessite PyAudioWPatch (pip install PyAudioWPatch) : PyAudio standard ne
sait pas ouvrir un flux WASAPI en loopback. Sans lui, la fonctionnalité
est simplement indisponible, l'enregistrement micro reste inchangé.

Particularité vérifiée sur Windows : un périphérique loopback ne délivre
AUCUNE donnée tant que rien ne joue (pas même du silence). En mode
bloquant, la lecture gèlerait ; seul le mode callback est utilisable, et
les trous doivent être comblés par du silence numérique à la sauvegarde
pour rester synchronisé avec la vidéo.
"""

import time
from typing import List, Optional

import numpy as np

try:
    import pyaudiowpatch
    WPATCH_AVAILABLE = True
except ImportError:  # pragma: no cover - dépend de l'environnement
    pyaudiowpatch = None
    WPATCH_AVAILABLE = False


def system_audio_is_available() -> bool:
    """True si la capture du son système est possible sur cette machine."""
    return WPATCH_AVAILABLE


def find_loopback_device() -> Optional[dict]:
    """Retourne le périphérique loopback du haut-parleur par défaut."""
    if not WPATCH_AVAILABLE:
        return None

    p = None
    try:
        p = pyaudiowpatch.PyAudio()
        wasapi = p.get_host_api_info_by_type(pyaudiowpatch.paWASAPI)
        default_out = p.get_device_info_by_index(wasapi['defaultOutputDevice'])

        loopbacks = list(p.get_loopback_device_info_generator())
        for device in loopbacks:
            if default_out['name'] in device['name']:
                return dict(device)
        return dict(loopbacks[0]) if loopbacks else None
    except Exception as e:
        print(f"[Lumina] Loopback indisponible: {e}")
        return None
    finally:
        if p is not None:
            try:
                p.terminate()
            except Exception:
                pass


class SystemAudioCapture:
    """Capture le son des haut-parleurs pendant l'enregistrement."""

    def __init__(self, gain: float = 1.0):
        self.gain = gain
        self.frames: List[bytes] = []
        self.sample_rate: Optional[int] = None
        self.channels: Optional[int] = None
        self._pa = None
        self._stream = None
        # Horodatage des chunks : le loopback ne délivre rien pendant les
        # silences, il faut savoir OÙ les trous se situent pour les combler
        self._timestamps: List[float] = []
        self._start_time: Optional[float] = None
        # Latence entre l'instant où un son sort des haut-parleurs et
        # celui où le loopback nous le livre. Mesurée au premier chunk
        # (voir on_chunk) et retranchée des horodatages : sans cela tout
        # le son système se retrouve en retard sur l'image.
        self._latence: float = 0.0

    def _apply_gain(self, data: bytes) -> bytes:
        if self.gain == 1.0:
            return data
        samples = np.frombuffer(data, dtype=np.int16)
        samples = np.clip(samples * self.gain, -32768, 32767).astype(np.int16)
        return samples.tobytes()

    def start(self, reference_time: Optional[float] = None) -> bool:
        """Ouvre le flux loopback. False si indisponible (jamais d'exception).

        `reference_time` (time.time() du début de l'enregistrement) permet
        de dater les chunks sur la même horloge que la vidéo. Sans lui,
        l'origine serait l'ouverture du loopback — postérieure de plus
        d'une seconde — et le son se retrouverait décalé.
        """
        device = find_loopback_device()
        if device is None:
            return False

        self.frames = []
        self._timestamps = []
        self._start_time = reference_time if reference_time else time.time()
        try:
            self._pa = pyaudiowpatch.PyAudio()
            self.sample_rate = int(device['defaultSampleRate'])
            self.channels = int(device['maxInputChannels'])

            # Horloge PortAudio : `input_buffer_adc_time` date le moment
            # où le matériel a RÉELLEMENT capté les échantillons, pas
            # celui où Python reçoit le callback. C'est la seule mesure
            # correcte : la livraison arrive avec un retard variable
            # (mesuré jusqu'à 2 s à l'ouverture du flux), et horodater à
            # l'arrivée décalait tout le son système par rapport à
            # l'image. On mémorise l'origine de cette horloge au premier
            # chunk pour la ramener sur celle de l'enregistrement.
            self._adc_origine = None

            def on_chunk(in_data, frame_count, time_info, status):
                adc = None
                try:
                    adc = float(time_info['input_buffer_adc_time'])
                except (KeyError, TypeError, ValueError):
                    pass

                if adc:
                    if self._adc_origine is None:
                        # Le premier chunk fixe la correspondance entre
                        # l'horloge PortAudio et celle de l'application.
                        # Son instant réel de capture est déduit du temps
                        # écoulé depuis le début de l'enregistrement,
                        # moins la latence de livraison observée.
                        ecoule = time.time() - self._start_time
                        duree = (frame_count / self.sample_rate
                                 if self.sample_rate else 0.0)
                        self._adc_origine = adc - max(0.0, ecoule - duree)
                    horodatage = adc - self._adc_origine
                else:
                    # Sans horloge matérielle : repli sur l'arrivée
                    horodatage = time.time() - self._start_time

                self._timestamps.append(horodatage)
                self.frames.append(self._apply_gain(in_data))
                return (None, pyaudiowpatch.paContinue)

            self._stream = self._pa.open(
                format=pyaudiowpatch.paInt16,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=device['index'],
                frames_per_buffer=1024,
                stream_callback=on_chunk)
            self._stream.start_stream()
            return True
        except Exception as e:
            print(f"[Lumina] Erreur capture son système: {e}")
            self.stop()
            return False

    def stop(self):
        """Ferme le flux et libère PortAudio."""
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    def get_audio_bytes(self, total_duration: Optional[float] = None) -> bytes:
        """Piste complète, silences compris.

        Le loopback WASAPI ne délivre aucune donnée tant que rien ne joue.
        Concaténer les chunks bruts collerait tout le son au début : une
        vidéo lancée après 5 s de navigation aurait son audio décalé de
        5 s. On réinsère donc le silence à sa place d'après l'horodatage
        des chunks, et on complète jusqu'à `total_duration` si fournie.
        """
        if not self.frames or not self.sample_rate or not self.channels:
            return b''

        bytes_per_frame = 2 * self.channels

        def silence(seconds: float) -> bytes:
            n = max(0, int(seconds * self.sample_rate))
            return b'\x00' * (n * bytes_per_frame)

        out = []
        position = 0.0   # instant de fin de l'audio déjà écrit
        for chunk, arrived_at in zip(self.frames, self._timestamps):
            chunk_duration = len(chunk) / bytes_per_frame / self.sample_rate
            # Le chunk couvre l'intervalle qui PRÉCÈDE son arrivée
            chunk_start = arrived_at - chunk_duration
            gap = chunk_start - position
            if gap > 0.01:          # trou réel : du silence a joué
                out.append(silence(gap))
                position += gap
            out.append(chunk)
            position += chunk_duration

        if total_duration and total_duration > position:
            out.append(silence(total_duration - position))

        return b''.join(out)
