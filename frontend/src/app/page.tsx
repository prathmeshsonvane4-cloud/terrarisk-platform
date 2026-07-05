import { About } from "@/components/landing/about";
import { Contact } from "@/components/landing/contact";
import { Features } from "@/components/landing/features";
import { Footer } from "@/components/landing/footer";
import { Header } from "@/components/landing/header";
import { Hero } from "@/components/landing/hero";

export default function Home() {
  return (
    <div className="flex min-h-screen flex-col">
      <Header />
      <main className="flex-1">
        <Hero />
        <Features />
        <About />
        <Contact />
      </main>
      <Footer />
    </div>
  );
}
