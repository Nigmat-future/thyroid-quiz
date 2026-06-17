const MAX_PRELOAD_CACHE = 3;
const preloadedImages = new Map();

function trimPreloadCache() {
  while (preloadedImages.size > MAX_PRELOAD_CACHE) {
    const [oldestUrl] = preloadedImages.keys();
    preloadedImages.delete(oldestUrl);
  }
}

export function clearImagePreloadCache() {
  preloadedImages.clear();
}

export function getPreloadedImageUrls() {
  return Array.from(preloadedImages.keys());
}

export function preloadImage(url, imageFactory = () => new Image()) {
  if (!url || preloadedImages.has(url)) return false;

  const img = imageFactory();
  img.decoding = "async";
  img.src = url;
  preloadedImages.set(url, img);
  trimPreloadCache();
  return true;
}

export function preloadNextQuestionImage(questions, currentIndex, imageFactory) {
  const next = questions?.[currentIndex + 1];
  return preloadImage(next?.image_url, imageFactory);
}
