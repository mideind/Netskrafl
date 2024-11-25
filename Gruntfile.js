
module.exports = function (grunt) {

   grunt.initConfig({

      ts: {
         default : {
            tsconfig: 'static/tsconfig.json',
            options: {
               rootDir: "static/src"
            }
         }
      },

      uglify: {
         explo_js: {
            src: 'static/built/explo.js',
            dest: 'static/built/explo.min.js'
         }
      },

      less: {
         development: {
            files: {
               'static/skrafl-explo.css': ['static/skrafl-explo.less']
            },
            options: {
            }
         },
         production: {
            files: {
               'static/skrafl-explo.css': ['static/skrafl-explo.less']
            },
            options: {
               cleancss: true
            }
         }
      },

      watch: {
         ts: {
            files: ['static/src/*.ts'],
            tasks: ['ts'],
            options: { spawn: false }
         },
         uglify_explo: {
            files: ['static/built/explo.js'],
            tasks: ['uglify:explo_js'],
            options: { spawn: false }
         },
         less: {
            files: ['static/*.less'],
            tasks: ['less:development', 'less:production'],
            options: { spawn: false }
         },
         configFiles: {
            files: 'Gruntfile.js'
         }
      }

   });

   // Load Grunt tasks declared in the package.json file
   require('matchdep').filterDev('grunt-*').forEach(grunt.loadNpmTasks);

   grunt.registerTask('default', ['watch']);
   grunt.registerTask('make', ['ts', 'uglify', 'less']);

   // On watch events configure jshint:all to only run on changed file
   grunt.event.on('watch', function(action, filepath) {
      console.log("watch: " + filepath);
      /*
      if (startsWith(filepath, "static/js/") || startsWith(filepath, "static\\js\\"))
         grunt.config('jshint.all.src', [ filepath ]);
      */
   });

};
