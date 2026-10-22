# Mio 18-frame slash animation

Generated with the built-in OpenAI image generation tool, using the existing original Mio sword mascot as the character reference. Source transparency is preserved. Runtime uses the PNG atlas and JSON crop rectangles; the 18-frame GIF is a looping preview on a light background.

- [PNG atlas](../assets/mio-slash-18.png)
- [Frame metadata](../assets/mio-slash-18.json)
- [GIF preview](../assets/mio-slash-18.gif)
- Exporter: `python3 scripts/export_slash_animation.py` (Pillow required only for export).

The app plays the sequence once only after a successful operation; it then holds/fades the last pose. Failed/cancelled/zero-success operations never play a success animation. Reduced motion keeps the static receipt. For disk deletion, impact cuts a snapshot of the selected tile into two halves, then into textured fragments; neighbouring tiles reflow only after the fragments clear (2.05 seconds). A 28 ms blend between the 18 poses and continuous motion follow the GTK frame clock. The snapshot retains the original filename, size, colour and selection border, and follows the tile bounds when the window resizes. Reduced motion skips the fragments and refreshes immediately. No animation performs filesystem mutations.

## Tile effect preview

Run `python3 -m scripts.preview_tile_shatter` in a graphical session (or Xvfb) to render `artifacts/mio-tile-shatter.gif` using the actual renderer and synthetic tiles. This preview never operates on files. Pillow is only needed for exporting the GIF.

## Initial prompt

Use case: stylized-concept. Production animation sprite sheet for Mio, the same original chibi feminine anime swordswoman in the reference image. Reference is character identity/style only. Create EXACTLY 18 distinct sequential animation frames arranged in EXACTLY 6 equal columns by 3 equal rows, read left to right then top to bottom. Entire canvas aspect ratio 2:1, ideally 3072x1536, each grid cell square. True transparent background. No visible grid, borders, labels, numbers, text, scenery, shadows on a floor, or extra characters. Each cell contains ONE complete full-body character and her sword, centered, consistent character scale and camera, with 10% transparent safety margin from every cell edge. Align feet baseline at 88% cell height and torso anchor at 50% cell width. Character: pink-to-periwinkle-blue long gradient hair, golden star hair clips, blue eyes, navy and white sailor fantasy dress, gold star details, white stockings, navy boots, luminous cyan sword. Preserve the reference's clean polished anime rendering and sweet closed mouth. Show a genuine continuous attack with different arm, leg, torso and hair poses in each frame, never repeated static poses. Frames 1-3: ready stance then crouch forward and start dash left. Frames 4-6: forward lunge, grip sword, draw sword up behind shoulder. Frames 7-9: windup overhead, body twists, sword starts descending. Frames 10-12: powerful diagonal slash toward lower left, luminous cyan/pink crescent blade trail only in these impact frames, fully contained in each cell. Frames 13-15: follow through, arm lowers, hair settles. Frames 16-18: sheath sword, rise to relaxed proud stance, tiny friendly smile. No gore, no victims. Frame-to-frame continuity, same character proportions, all weapons and effects fully inside each cell. This is ONE sprite sheet asset, not a comic or a collage.

## Atlas spacing correction prompt

Edit this 18-frame sprite sheet for reliable game-engine grid slicing. Keep exactly the same 18 poses, same pink-blue chibi girl, outfit, sword, art style and sequence. CRITICAL FIX: the sprites currently touch neighboring cells. Re-layout as EXACTLY 6 equal columns and 3 equal rows in a 2:1 canvas. Each invisible cell contains only its own one complete character and sword. SHRINK EACH SPRITE TO 70% OF ITS CURRENT CELL SIZE, including all long hair, blade and effects. Center each sprite in its cell. Leave AT LEAST 15% of each cell width as EMPTY TRANSPARENT PADDING on both left and right, and 15% cell height on both top and bottom. Nothing can touch or cross any cell boundary. Use the full transparent canvas with no cropping of outside margins. Maintain consistent head size and feet baseline across frames. No visible grid, no cell borders, no text, no numbering. All background and padding truly transparent. This is a technical sprite atlas correction, not a new pose sequence.

