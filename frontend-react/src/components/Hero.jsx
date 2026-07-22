import { motion } from "framer-motion";

function Hero() {
  return (

    <motion.div

      initial={{opacity:0,y:50}}

      animate={{opacity:1,y:0}}

      transition={{duration:1}}

      className="text-center mt-24"

    >

      <h1 className="text-6xl font-bold text-white">

        Understand Documents

      </h1>

      <p className="mt-6 text-slate-400 text-xl">

        AI powered document summarizer with citations.

      </p>

    </motion.div>

  );
}

export default Hero;