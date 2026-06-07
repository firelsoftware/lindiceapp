const createBanner = (accentA, accentB, label) => {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 900">
      <defs>
        <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stop-color="${accentA}" />
          <stop offset="100%" stop-color="${accentB}" />
        </linearGradient>
      </defs>
      <rect width="1600" height="900" fill="url(#bg)" />
      <circle cx="1230" cy="140" r="220" fill="rgba(255,255,255,0.12)" />
      <circle cx="260" cy="770" r="280" fill="rgba(255,255,255,0.08)" />
      <path d="M980 120C1120 220 1180 330 1260 460C1340 590 1450 650 1600 690V900H0V650C180 610 320 560 450 430C580 300 720 170 980 120Z" fill="rgba(255,255,255,0.08)" />
      <text x="120" y="150" fill="rgba(255,255,255,0.68)" font-family="Arial, sans-serif" font-size="36" letter-spacing="10">${label}</text>
      <text x="120" y="760" fill="rgba(255,255,255,0.82)" font-family="Georgia, serif" font-size="92">Banner Lindice</text>
      <text x="120" y="830" fill="rgba(255,255,255,0.66)" font-family="Arial, sans-serif" font-size="30">Imagem provisoria para campanha, vitrine e destaque de colecao.</text>
    </svg>
  `;

  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
};

export const heroSlides = [
  {
    id: "lancamentos",
    eyebrow: "Nova vitrine",
    title: "Moda com cara de campanha logo no primeiro segundo.",
    description:
      "Hero fullscreen com imagem total, leitura premium e espaco pronto para banners reais da Lindice.",
    image: createBanner("#4d63b7", "#7a2d84", "LANCAMENTO"),
  },
  {
    id: "colecao",
    eyebrow: "Colecao em destaque",
    title: "Uma abertura limpa, sofisticada e feita para vender mais.",
    description:
      "A estrutura une vitrine de marca, navegacao clara e chamadas de compra sem poluir o topo.",
    image: createBanner("#24367b", "#4d63b7", "COLECAO"),
  },
  {
    id: "crediario",
    eyebrow: "Compra facilitada",
    title: "Da inspiracao ao crediario digital em uma unica experiencia.",
    description:
      "O visitante entende o valor da marca e encontra o caminho para compra ou cadastro sem atrito.",
    image: createBanner("#7a2d84", "#4d63b7", "CREDIARIO"),
  },
];
