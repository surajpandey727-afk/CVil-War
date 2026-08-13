/**
 * The CVil-War mark.
 *
 * Served from `public/` at three sizes rather than one, because the source artwork is
 * 1254×1254 / 1.9 MB — shipping that for a 28 px sidebar icon would dominate the page weight.
 * The nearest size up from the requested render size is chosen so the image is never upscaled.
 */

const SIZES = [128, 256, 512] as const;

interface LogoProps {
  /** Rendered edge length in CSS pixels. */
  size?: number;
  /** Rounded-corner radius. Defaults to a squircle proportional to `size`. */
  radius?: number;
  className?: string;
}

/** Smallest shipped asset that is at least 2× the render size, for high-DPI displays. */
function assetFor(size: number): string {
  const wanted = size * 2;
  const pick = SIZES.find((s) => s >= wanted) ?? SIZES[SIZES.length - 1]!;
  return `/logo-${pick}.png`;
}

export default function Logo({ size = 32, radius, className }: LogoProps) {
  return (
    <img
      src={assetFor(size)}
      width={size}
      height={size}
      alt="CVil-War"
      className={className}
      style={{
        width: size,
        height: size,
        borderRadius: radius ?? Math.round(size * 0.28),
        display: 'block',
        objectFit: 'cover',
        flex: '0 0 auto',
      }}
    />
  );
}
