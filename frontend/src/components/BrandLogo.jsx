export default function BrandLogo({ className = "h-10 w-10" }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 64 64"
      fill="none"
      role="img"
      aria-label="شعار شفاء جايد — ShefaGuide AI"
      className={className}
    >
      <defs>
        <linearGradient
          id="shefa-brand-grad"
          x1="6"
          y1="6"
          x2="58"
          y2="58"
          gradientUnits="userSpaceOnUse"
        >
          <stop offset="0%" stopColor="#0D9488" />
          <stop offset="55%" stopColor="#0F766E" />
          <stop offset="100%" stopColor="#4F46E5" />
        </linearGradient>
      </defs>

      <path
        d="M32 4.5C21.5 4.5 11 8.5 8.5 10.2C7.4 10.9 6.8 12.1 6.8 13.4V29.6C6.8 44.3 17.5 54.4 30.6 59.1C31.5 59.4 32.5 59.4 33.4 59.1C46.5 54.4 57.2 44.3 57.2 29.6V13.4C57.2 12.1 56.6 10.9 55.5 10.2C53 8.5 42.5 4.5 32 4.5Z"
        fill="url(#shefa-brand-grad)"
      />
      <path
        d="M28.5 17.5C28.5 16.4 29.4 15.5 30.5 15.5H33.5C34.6 15.5 35.5 16.4 35.5 17.5V26.5H44.5C45.6 26.5 46.5 27.4 46.5 28.5V31.5C46.5 32.6 45.6 33.5 44.5 33.5H35.5V42.5C35.5 43.6 34.6 44.5 33.5 44.5H30.5C29.4 44.5 28.5 43.6 28.5 42.5V33.5H19.5C18.4 33.5 17.5 32.6 17.5 31.5V28.5C17.5 27.4 18.4 26.5 19.5 26.5H28.5V17.5Z"
        fill="#FFFFFF"
        fillOpacity="0.18"
      />
      <path
        d="M13.5 31H21.2L24.8 23.2L30.2 40.5L35.6 21.8L39.6 31H50.5"
        stroke="#FFFFFF"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M46.5 13.5L47.7 16.8L51 18L47.7 19.2L46.5 22.5L45.3 19.2L42 18L45.3 16.8L46.5 13.5Z"
        fill="#A7F3D0"
      />
    </svg>
  );
}
