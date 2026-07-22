import { FileText } from "lucide-react";

function Navbar() {
  return (
    <nav className="w-full border-b border-slate-800 bg-slate-950/80 backdrop-blur-md">
      <div className="max-w-7xl mx-auto flex items-center justify-between px-8 py-5">

        <div className="flex items-center gap-3">

          <div className="w-10 h-10 rounded-xl bg-cyan-500 flex items-center justify-center">

            <FileText className="text-black"/>

          </div>

          <h1 className="text-2xl font-bold text-white">
            Marginal AI
          </h1>

        </div>

        <button className="px-5 py-2 rounded-xl bg-cyan-500 text-black font-semibold hover:scale-105 transition">
          Dashboard
        </button>

      </div>
    </nav>
  );
}

export default Navbar;