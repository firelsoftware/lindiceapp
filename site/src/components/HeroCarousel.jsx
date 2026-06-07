import { useEffect, useMemo, useState } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { heroSlides } from "../data/slides";

const AUTOPLAY_MS = 4000;

export function HeroCarousel() {
  const [emblaRef, emblaApi] = useEmblaCarousel({ loop: true, duration: 30 });
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const [parallaxOffset, setParallaxOffset] = useState(0);

  const slides = useMemo(() => heroSlides, []);

  useEffect(() => {
    if (!emblaApi) {
      return undefined;
    }

    const onSelect = () => {
      setSelectedIndex(emblaApi.selectedScrollSnap());
    };

    onSelect();
    emblaApi.on("select", onSelect);
    emblaApi.on("reInit", onSelect);

    return () => {
      emblaApi.off("select", onSelect);
      emblaApi.off("reInit", onSelect);
    };
  }, [emblaApi]);

  useEffect(() => {
    if (!emblaApi || paused) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      emblaApi.scrollNext();
    }, AUTOPLAY_MS);

    return () => window.clearInterval(timer);
  }, [emblaApi, paused]);

  useEffect(() => {
    const onScroll = () => {
      setParallaxOffset(Math.min(window.scrollY * 0.12, 60));
    };

    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });

    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const scrollTo = (index) => emblaApi && emblaApi.scrollTo(index);
  const scrollPrev = () => emblaApi && emblaApi.scrollPrev();
  const scrollNext = () => emblaApi && emblaApi.scrollNext();

  return (
    <header
      className="relative isolate flex min-h-screen w-full overflow-hidden bg-slate-950"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocusCapture={() => setPaused(true)}
      onBlurCapture={() => setPaused(false)}
    >
      <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
        <div className="embla h-full" ref={emblaRef}>
          <div className="embla__container h-full">
            {slides.map((slide, index) => (
              <div className="embla__slide relative h-full min-w-0 flex-[0_0_100%]" key={slide.id}>
                <div
                  className={`absolute inset-0 scale-[1.08] bg-cover bg-center bg-no-repeat transition-opacity duration-700 ${
                    selectedIndex === index ? "opacity-100" : "opacity-0"
                  }`}
                  style={{
                    backgroundImage: `url("${slide.image}")`,
                    transform: `scale(1.08) translateY(${parallaxOffset}px)`,
                  }}
                />
              </div>
            ))}
          </div>
        </div>
        <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(10,16,32,0.38),rgba(10,16,32,0.58)_38%,rgba(10,16,32,0.82))]" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top,rgba(159,181,202,0.18),transparent_32%)]" />
      </div>

      <div className="relative z-10 flex w-full flex-col">
        <div className="mx-auto flex w-full max-w-7xl items-center justify-between px-5 py-5 md:px-8 lg:px-10">
          <a href="#hero" className="flex items-center gap-4" aria-label="Lindice">
            <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-lindice-blue to-lindice-purple text-xl font-black text-white shadow-glow">
              L
            </span>
            <span className="hidden text-left sm:grid">
              <strong className="font-display text-2xl font-semibold tracking-[-0.04em] text-white">Lindice</strong>
              <span className="text-xs uppercase tracking-[0.24em] text-white/60">Moda, loja e crediario</span>
            </span>
          </a>

          <nav className="hidden items-center gap-8 text-sm font-semibold text-white/74 lg:flex">
            <a className="transition hover:text-white" href="#colecao">Colecao</a>
            <a className="transition hover:text-white" href="#vitrine">Vitrine</a>
            <a className="transition hover:text-white" href="#crediario">Crediario</a>
          </nav>

          <div className="flex items-center gap-3">
            <a
              href="https://app.lindice.com.br/login/"
              className="hidden rounded-full border border-white/18 bg-white/8 px-5 py-3 text-sm font-semibold text-white backdrop-blur md:inline-flex"
            >
              Entrar
            </a>
            <a
              href="https://app.lindice.com.br/loja/"
              className="inline-flex rounded-full bg-white px-5 py-3 text-sm font-bold text-lindice-ink shadow-[0_14px_40px_rgba(255,255,255,0.18)]"
            >
              Comprar agora
            </a>
          </div>
        </div>

        <section
          id="hero"
          className="mx-auto flex w-full max-w-7xl flex-1 items-center px-5 pb-10 pt-8 md:px-8 md:pb-14 lg:px-10"
        >
          <div className="grid w-full gap-10 lg:grid-cols-[minmax(0,1.05fr)_minmax(280px,0.58fr)] lg:items-end">
            <div className="max-w-4xl">
              <div className="overflow-hidden">
                <p
                  key={`eyebrow-${slides[selectedIndex].id}`}
                  className="animate-fade-up text-xs font-black uppercase tracking-[0.34em] text-lindice-mist"
                >
                  {slides[selectedIndex].eyebrow}
                </p>
              </div>
              <div className="overflow-hidden">
                <h1
                  key={`title-${slides[selectedIndex].id}`}
                  className="animate-fade-up pt-4 font-display text-5xl font-semibold leading-[0.92] tracking-[-0.06em] text-white sm:text-6xl md:text-7xl lg:text-[5.5rem]"
                >
                  {slides[selectedIndex].title}
                </h1>
              </div>
              <div className="overflow-hidden">
                <p
                  key={`description-${slides[selectedIndex].id}`}
                  className="animate-fade-up max-w-2xl pt-6 text-base leading-8 text-white/72 sm:text-lg"
                >
                  {slides[selectedIndex].description}
                </p>
              </div>

              <div className="animate-fade-up flex flex-wrap gap-4 pt-8">
                <a
                  href="https://app.lindice.com.br/loja/"
                  className="inline-flex min-h-14 items-center rounded-full bg-gradient-to-r from-lindice-blue to-lindice-purple px-7 text-sm font-bold text-white shadow-[0_18px_60px_rgba(77,99,183,0.35)]"
                >
                  Explorar a loja
                </a>
                <a
                  href="https://app.lindice.com.br/cadastro/?intent=credit"
                  className="inline-flex min-h-14 items-center rounded-full border border-white/18 bg-white/10 px-7 text-sm font-bold text-white backdrop-blur"
                >
                  Pedir crediario
                </a>
              </div>
            </div>

            <div
              id="vitrine"
              className="animate-fade-up rounded-[2rem] border border-white/14 bg-white/10 p-5 shadow-glow backdrop-blur-xl"
            >
              <div className="rounded-[1.5rem] border border-white/10 bg-black/20 p-5">
                <p className="text-xs font-black uppercase tracking-[0.26em] text-lindice-mist">Primeira impressao</p>
                <p className="pt-4 font-display text-3xl font-semibold leading-tight text-white">
                  Hero premium, leve e pronto para banners reais.
                </p>
                <p className="pt-4 text-sm leading-7 text-white/66">
                  Carrossel em tela cheia, pause no hover, navegacao acessivel e estrutura ideal para campanhas.
                </p>
                <div className="mt-6 grid gap-3 text-sm text-white/72">
                  <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">100vh fullscreen</div>
                  <div className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">Fade suave a cada 4 segundos</div>
                  <div id="crediario" className="rounded-2xl border border-white/10 bg-white/6 px-4 py-3">Overlay, parallax e CTA forte</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <div className="mx-auto flex w-full max-w-7xl items-center justify-between gap-4 px-5 pb-6 md:px-8 lg:px-10">
          <div className="flex items-center gap-2.5" role="tablist" aria-label="Indicadores do banner principal">
            {slides.map((slide, index) => (
              <button
                key={slide.id}
                type="button"
                aria-label={`Mostrar slide ${index + 1}`}
                aria-selected={selectedIndex === index}
                className={`h-3 rounded-full transition-all ${
                  selectedIndex === index ? "w-10 bg-white" : "w-3 bg-white/35 hover:bg-white/60"
                }`}
                onClick={() => scrollTo(index)}
              />
            ))}
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="Slide anterior"
              className="flex h-12 w-12 items-center justify-center rounded-full border border-white/14 bg-white/10 text-2xl text-white backdrop-blur transition hover:bg-white/18"
              onClick={scrollPrev}
            >
              <span aria-hidden="true">&lsaquo;</span>
            </button>
            <button
              type="button"
              aria-label="Proximo slide"
              className="flex h-12 w-12 items-center justify-center rounded-full border border-white/14 bg-white/10 text-2xl text-white backdrop-blur transition hover:bg-white/18"
              onClick={scrollNext}
            >
              <span aria-hidden="true">&rsaquo;</span>
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
