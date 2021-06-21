
module.exports = function (grunt) {

   grunt.initConfig({

      // See: http://www.jshint.com/docs/
      jshint: {
         all: {
            options: {
               bitwise: true,
               camelcase: false,
               curly: false,
               eqeqeq: false,
               forin: true,
               freeze: true,
               immed: true,
               indent: 3,
               latedef: 'nofunc',
               newcap: true,
               noarg: true,
               noempty: true,
               nonew: true,
               regexp: true,
               undef: true,
               validthis: true,
               unused: false,
               maxlen: 120
            }
         }
      },

      ts: {
         default : {
           tsconfig: 'static/tsconfig.json',
           options: {
              rootDir: "static/src"
           }
         }
      },

      concat: {
         /*
         netskrafl_js: {
            src: [
               'static/js/common.js',
               'static/js/channel.js',
               'static/js/ajax.js',
               'static/js/ui.js',
               'static/js/netskrafl.js'
            ],
            dest: 'static/netskrafl.js',
         },
         main_js: {
            src: [
               'static/js/common.js',
               'static/js/channel.js',
               'static/js/ajax.js',
               'static/js/ui.js',
               'static/js/main.js'
            ],
            dest: 'static/main.js',
         },
         wait_js: {
            src: [
               'static/js/channel.js',
               'static/js/ajax.js',
               'static/js/ui.js',
               'static/js/wait.js'
            ],
            dest: 'static/wait.js',
         }
         */
      },

      uglify: {
         page_js: {
            src: 'static/built/page.js',
            dest: 'static/built/page.min.js'
         },
         game_js: {
            src: 'static/built/game.js',
            dest: 'static/built/game.min.js'
         },
         channel_js: {
            src: 'static/built/channel.js',
            dest: 'static/built/channel.min.js'
         },
         wait_js: {
            src: 'static/built/wait.js',
            dest: 'static/built/wait.min.js'
         },
         util_js: {
            src: 'static/built/util.js',
            dest: 'static/built/util.min.js'
         }
      },

      less: {
         development: {
            files: {
               'static/skrafl-curry.css': ['static/skrafl-curry.less'],
               'static/skrafl-desat.css': ['static/skrafl-desat.less'],
               'static/skrafl-explo.css': ['static/skrafl-explo.less']
            },
            options: {
            }
         },
         production: {
            files: {
               'static/skrafl-curry.css': ['static/skrafl-curry.less'],
               'static/skrafl-desat.css': ['static/skrafl-desat.less'],
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
         /*
         concat: {
            files: ['static/js/*.js'],
            tasks: ['concat']
         },
         */
         /*
         jshint: {
            files: ['static/js/*.js'],
            tasks: ['jshint'],
            options: { spawn: false }
         },
         */
         uglify_page: {
            files: ['static/built/page.js'],
            tasks: ['uglify:page_js'],
            options: { spawn: false }
         },
         uglify_game: {
            files: ['static/built/game.js'],
            tasks: ['uglify:game_js'],
            options: { spawn: false }
         },
         uglify_channel: {
            files: ['static/built/channel.js'],
            tasks: ['uglify:channel_js'],
            options: { spawn: false }
         },
         uglify_util: {
            files: ['static/built/util.js'],
            tasks: ['uglify:util_js'],
            options: { spawn: false }
         },
         uglify_wait: {
            files: ['static/built/wait.js'],
            tasks: ['uglify:wait_js'],
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
   grunt.registerTask('make', ['ts', /* 'concat', */ 'uglify', 'less']);

   function startsWith(s, t) {
      return s.lastIndexOf(t, 0) === 0;
   }

   // On watch events configure jshint:all to only run on changed file
   grunt.event.on('watch', function(action, filepath) {
      console.log("watch: " + filepath);
      /*
      if (startsWith(filepath, "static/js/") || startsWith(filepath, "static\\js\\"))
         grunt.config('jshint.all.src', [ filepath ]);
      */
   });

};
