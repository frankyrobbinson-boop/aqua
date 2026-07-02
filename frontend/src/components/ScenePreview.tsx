/**
 * Renders a scene's footage by extension: image extensions (.png/.jpg/.webp/
 * .gif) render as <img>, everything else (Pexels .mp4) as a muted <video>.
 * Renders a "No footage" placeholder when url is null. Shared between the
 * project Scenes grid (SceneCard) and the Visuals wizard previews so the
 * extension-sniffing render logic lives in exactly one place.
 */
type Props = {
  url: string | null;
  alt: string;
  className?: string;
};

export function ScenePreview({ url, alt, className }: Props) {
  const cls = className ?? "h-full w-full object-cover";
  if (!url) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted">
        No footage
      </div>
    );
  }
  const isImage = /\.(png|jpe?g|webp|gif)(\?|$)/i.test(url);
  return isImage ? (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={alt} className={cls} />
  ) : (
    <video
      src={`${url}#t=0.1`}
      muted
      playsInline
      preload="metadata"
      controls
      className={cls}
    />
  );
}
