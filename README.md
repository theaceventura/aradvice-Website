# Andrew Roberts Advisory Website

A professional multi-page advisory website for cyber and AI governance consulting services.

## Features

- 🎨 **Modern Dark Theme** with neon cyan accents
- 📱 **Fully Responsive** - works perfectly on all devices
- ⚡ **Tailwind CSS** via CDN (no build process needed)
- 🎭 **Material Symbols** icons
- 🖼️ **Full-screen hero sections** with background images
- 💎 **Glass morphism effects** and smooth animations
- 📧 **Pre-configured mailto** links for contact (hello@aradvice.com.au)
- 🔗 **Multi-page navigation** - Home, Readiness Review, Resource Hub

## Tech Stack

- **HTML5** - Semantic markup
- **Tailwind CSS 3** - Utility-first CSS framework (CDN)
- **Google Fonts** - Inter font family
- **Material Symbols** - Icon library

## Getting Started

### Option 1: Simple HTTP Server (Python) ✅ RECOMMENDED

```bash
# Navigate to your project folder
cd my-website

# Start a simple web server (Python 3)
python3 -m http.server 8000
```

Then open your browser to: **http://localhost:8000**

### Option 2: VS Code Live Server

1. Install the "Live Server" extension in VS Code
2. Right-click on `index.html`
3. Select "Open with Live Server"

### Option 3: Just Open the File

Simply double-click `index.html` to open it in your browser.

## Project Structure

```
my-website/
├── index.html               # Homepage - main landing page
├── readiness-review.html    # Governance Readiness Review service page
├── resource-hub.html        # Director's Resource Hub with frameworks
├── privacy-policy.html      # Privacy Policy (Australian Privacy Act compliant)
├── terms-of-service.html    # Terms of Service (Australian jurisdiction)
├── liability-disclaimer.html # Professional liability disclaimer
├── .gitignore              # Git ignore file
└── README.md               # This file
```

**Note:** This website uses Tailwind CSS via CDN and has all styles inline, so no separate CSS or JS files are needed!

## Site Pages

### 1. Homepage (index.html)
- Hero section with value proposition
- "Why Boards Are Exposed" - 4 key risk areas
- Board-Level Advisory services (4 service offerings)
- Independent Advisory positioning
- Governance frameworks reference
- Contact CTA

### 2. Readiness Review (readiness-review.html)
- 48-hour diagnostic service overview
- 3-step process explanation
- 4 key deliverables
- "Why Now" section with regulatory context
- Contact form integration

### 3. Resource Hub (resource-hub.html)
- AICD governance principles breakdown
- Cyber security strategy frameworks
- Risk management resources  
- AI governance checklist
- External links to AICD, ASIC, OAIC resources
- Contact form for governance review bookings and expert consultations

### 4. Privacy Policy (privacy-policy.html)
- Compliant with Privacy Act 1988 (Cth) and Australian Privacy Principles
- Information collection and usage disclosure
- Data security and retention policies
- User rights under Australian law
- OAIC complaint procedures

### 5. Terms of Service (terms-of-service.html)
- Professional advisory engagement terms
- Service descriptions and scope
- Fee structures and payment terms
- Confidentiality and IP provisions
- Australian Consumer Law compliance
- Victorian jurisdiction

### 6. Liability Disclaimer (liability-disclaimer.html)
- Professional service limitations
- Distinction from legal/regulatory advice
- Client responsibility framework
- Third-party resource disclaimers
- Professional indemnity insurance disclosure
- Australian corporate governance accountability context

## Customization Guide

### 1. Update Business Details

**IMPORTANT:** Update the following placeholders in legal pages:

In `privacy-policy.html`, `terms-of-service.html`, and `liability-disclaimer.html`:
- Replace `[Your ABN Number]` with your Australian Business Number
- Replace `[Your ACN Number]` with your Australian Company Number (if applicable)

These appear in the contact sections at the bottom of each legal page.

### 2. Update Contact Email

Find and replace `hello@aradvice.com.au` with your actual email address throughout the site.

### 3. Change Brand Colors

In the `<script id="tailwind-config">` section at the top of index.html:

```javascript
colors: {
  primary: "#00d4ff",        // Neon cyan - change this
  "navy-deep": "#050b1a",    // Dark background
  "navy-rich": "#0a1428",    // Slightly lighter background
}
```

### 4. Replace Background Images

The site uses Google-hosted images. To use your own:
1. Create an `images/` folder
2. Add your images there
3. Update the `src` attributes in each section's `<img>` tag

Example:
```html
<img src="images/hero-background.jpg" alt="Description" />
```

### 5. Update Content

All text content is directly in the HTML. Search for:
- **Company name**: "Andrew Roberts Advisory"
- **Services**: The 4 service cards in the `#services` section
- **Taglines**: Update the hero headline and subheadlines

### 6. Add Mobile Menu Functionality

The mobile menu button exists but needs JavaScript. Add smooth scroll after the closing `</footer>` tag:

```html
<script>
// Smooth scrolling for anchor links
do Deployment Options

### GitHub Pages (Recommended for Beginners)

1. Create a GitHub account and repository
2. Push your code:
   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/yourusername/your-repo.git
   git push -u origin main
   ```
3. Go to Settings → Pages → Select "main" branch
4. Your site will be live at `https://yourusername.github.io/your-repo/`

### Netlify (Easiest Drag & Drop)

1. Go to [netlify.com](https://netlify.com)
2. Drag your `my-website` folder into the deploy zone
3. Done! You get a live URL instantly

### Vercel

1. Install Vercel CLI: `npm i -g vercel`
2. Run `vercel` in your project folder
3. Follow the prompts

## Performance Tips

- All assets load from CDN (fast global delivery)
- Multiple pages with consistent navigation
- Background images are optimized via Google's CDN
- No build process = instant deployment

## Browser Compatibility

- ✅ Chrome/Edge (latest)
- ✅ Firefox (latest)
- ✅ Safari (latest)
- ✅ Mobile browsers (iOS Safari, Chrome Mobile)

## License

This is your website - customize it however you like!

---

**Need help?** Check the HTML comments or search for Tailwind CSS classes at [tailwindcss.com](https://tailwindcss.com)
