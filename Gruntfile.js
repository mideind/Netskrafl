module.exports = function (grunt) {

   grunt.initConfig({

      ts: {
         // Note: this seems to be not working well under grunt-ts,
         // giving a tsc warning about use of the 'out' option
         // (which is not present in tsconfig.json) and stopping compilation.
         default : {
            tsconfig: "static/tsconfig.json",
            options: {
               rootDir: "static",
            },
         },
      },

      exec: {
         // This, however, works well with tsc 5.7.2
         tsc: {
            cwd: "static",
            command: "tsc",
            stdout: true,
            stderr: true
         }
      },

      uglify: {
         explo_js: {
            options: {
               sourceMap: true // Add source maps
            },
            src: "static/built/explo.js",
            dest: "static/built/explo.min.js"
         }
      },

      less: {
         development: {
            files: {
               "static/skrafl-explo.css": ["static/skrafl-explo.less"]
            },
            options: {
            }
         },
         production: {
            files: {
               "static/skrafl-explo.css": ["static/skrafl-explo.less"]
            },
            options: {
               cleancss: true
            }
         }
      },

      clean: {
         built: ["static/built/*"]
      },

      watch: {
         options: {
            spawn: false,
            interrupt: true, // Interrupt previous tasks when new changes occur
            atBegin: true // Run tasks when watch starts
         },
         ts: {
            files: ["static/src/*.ts"],
            tasks: ["ts"],
            options: { spawn: false }
         },
         uglify_explo: {
            files: ["static/built/explo.js"],
            tasks: ["uglify:explo_js"],
            options: { spawn: false }
         },
         less: {
            files: ["static/*.less"],
            tasks: ["less:development", "less:production"],
            options: { spawn: false }
         },
         configFiles: {
            files: "Gruntfile.js"
         }
      }

   });

   // Load Grunt tasks declared in the package.json file
   require("matchdep").filterDev("grunt-*").forEach(grunt.loadNpmTasks);

   grunt.registerTask("default", ["watch"]);
   grunt.registerTask("make", ["clean", "exec:tsc", "uglify", "less"]);

   // On watch events configure jshint:all to only run on changed file
   grunt.event.on("watch", function(action, filepath) {
      console.log("watch: " + filepath);
      /*
      if (startsWith(filepath, "static/js/") || startsWith(filepath, "static\\js\\"))
         grunt.config("jshint.all.src", [ filepath ]);
      */
   });

};
