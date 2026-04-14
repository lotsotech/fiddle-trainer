"""
Convert SF2 soundfont to ABCJS-compatible midi-js-soundfonts format.
Requires: pip install pyfluidsynth numpy
Requires: fluidsynth installed (apt install fluidsynth OR choco install fluidsynth)

Usage: python convert_sf2.py input.sf2 output_dir instrument_name
Example: python convert_sf2.py custom_violin.sf2 ./soundfonts/custom-violin violin
"""
import sys
import os
import struct
import wave
import subprocess
import base64
import tempfile

def render_note_fluidsynth(sf2_path, midi_note, duration_ms=2000, sample_rate=22050):
    """Render a single MIDI note from SF2 using fluidsynth CLI."""
    with tempfile.NamedTemporaryFile(suffix='.mid', delete=False) as mf:
        midi_path = mf.name
        # Create a minimal MIDI file with one note
        write_midi_note(mf, midi_note, duration_ms)

    wav_path = midi_path.replace('.mid', '.wav')

    # Use fluidsynth to render
    cmd = [
        'fluidsynth', '-ni', sf2_path, midi_path,
        '-F', wav_path,
        '-r', str(sample_rate),
        '-g', '1.0'
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=10)

    os.unlink(midi_path)

    if os.path.exists(wav_path) and os.path.getsize(wav_path) > 100:
        return wav_path
    return None

def write_midi_note(f, note, duration_ms):
    """Write a minimal MIDI file with a single note."""
    import struct

    # MIDI file header
    f.write(b'MThd')  # Header chunk
    f.write(struct.pack('>I', 6))  # Header length
    f.write(struct.pack('>HHH', 0, 1, 480))  # Format 0, 1 track, 480 ticks/beat

    # Track chunk
    track_data = bytearray()

    # Tempo: 500000 microseconds per beat (120 BPM)
    track_data.extend(b'\x00\xff\x51\x03')
    track_data.extend(struct.pack('>I', 500000)[1:])

    # Note on
    track_data.extend(b'\x00\x90')
    track_data.append(note)
    track_data.append(100)  # velocity

    # Note off after duration
    ticks = int(duration_ms * 480 / 500)
    # Variable length encoding
    if ticks < 128:
        track_data.append(ticks)
    else:
        track_data.append(0x80 | ((ticks >> 7) & 0x7f))
        track_data.append(ticks & 0x7f)

    track_data.extend(b'\x80')
    track_data.append(note)
    track_data.append(0)

    # End of track
    track_data.extend(b'\x00\xff\x2f\x00')

    f.write(b'MTrk')
    f.write(struct.pack('>I', len(track_data)))
    f.write(track_data)

def wav_to_mp3_base64(wav_path):
    """Convert WAV to MP3 and return base64 string."""
    mp3_path = wav_path.replace('.wav', '.mp3')

    # Try ffmpeg first, then lame
    for cmd in [
        ['ffmpeg', '-y', '-i', wav_path, '-b:a', '64k', '-ar', '22050', mp3_path],
        ['lame', '--quiet', '-b', '64', wav_path, mp3_path]
    ]:
        try:
            subprocess.run(cmd, capture_output=True, timeout=10)
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 100:
                with open(mp3_path, 'rb') as f:
                    b64 = base64.b64encode(f.read()).decode()
                os.unlink(mp3_path)
                os.unlink(wav_path)
                return b64
        except FileNotFoundError:
            continue

    # Fallback: use WAV directly (larger but works)
    with open(wav_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode()
    os.unlink(wav_path)
    return b64

def main():
    if len(sys.argv) < 4:
        print(f"Usage: {sys.argv[0]} input.sf2 output_dir instrument_name")
        print(f"Example: {sys.argv[0]} custom_violin.sf2 ./soundfonts/custom-violin violin")
        sys.exit(1)

    sf2_path = sys.argv[1]
    output_dir = sys.argv[2]
    instrument_name = sys.argv[3]

    os.makedirs(output_dir, exist_ok=True)

    note_names = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

    print(f"Converting {sf2_path} to midi-js-soundfonts format...")
    print(f"Output: {output_dir}/{instrument_name}-mp3.js")

    samples = {}

    # Render MIDI notes 36 (C2) to 108 (C8) - covers all instruments
    for midi_note in range(36, 109):
        octave = (midi_note // 12) - 1
        note_name = note_names[midi_note % 12]
        display_name = f"{note_name}{octave}"

        print(f"  Rendering {display_name} (MIDI {midi_note})...", end=' ')

        wav_path = render_note_fluidsynth(sf2_path, midi_note)
        if wav_path:
            b64 = wav_to_mp3_base64(wav_path)
            if b64:
                samples[display_name] = b64
                print("OK")
            else:
                print("FAILED (encode)")
        else:
            print("FAILED (render)")

    # Write JS file in midi-js-soundfonts format
    js_path = os.path.join(output_dir, f"{instrument_name}-mp3.js")
    with open(js_path, 'w') as f:
        f.write('if (typeof(MIDI) === "undefined") var MIDI = {};\n')
        f.write('if (typeof(MIDI.Soundfont) === "undefined") MIDI.Soundfont = {};\n')
        f.write(f'MIDI.Soundfont.{instrument_name} = {{\n')

        entries = []
        for name, b64 in sorted(samples.items(), key=lambda x: note_sort_key(x[0])):
            entries.append(f'  "{name}": "data:audio/mp3;base64,{b64}"')

        f.write(',\n'.join(entries))
        f.write('\n};\n')

    print(f"\nDone! {len(samples)} notes written to {js_path}")
    print(f"File size: {os.path.getsize(js_path) / 1024 / 1024:.1f} MB")

def note_sort_key(name):
    """Sort notes chromatically."""
    note_order = {'C':0,'Db':1,'D':2,'Eb':3,'E':4,'F':5,'Gb':6,'G':7,'Ab':8,'A':9,'Bb':10,'B':11}
    for n in sorted(note_order.keys(), key=lambda x: -len(x)):
        if name.startswith(n):
            octave = int(name[len(n):])
            return octave * 12 + note_order[n]
    return 999

if __name__ == '__main__':
    main()
