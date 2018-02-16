
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
               unused: false,
               maxlen: 120,
               predef: ['$', 'm', 'document', 'window', 'alert', 'console', 'Mousetrap',
                  'localPlayer', 'placeTiles', 'initBag', 'initMoveList',
                  'gameId', 'userId', 'opponentId', 'jQuery', 'newgameUrl', 'waitUrl',
                  'goToGame', 'cancelWait', 'lateInit', 'initialGameTime', 'goog',
                  'replaceEmoticons', 'gameIsZombie', 'fbShare', 'localStorage',
                  'gameIsFairplay', 'fairPlay', 'navToUserprefs', 'opponentInfo',
                  'gameUrl', 'gameUsesNewBag', 'newBag', 'gameIsManual', '$state',
                  'firebase'
               ]
            }
         }
      },

      concat: {
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
      },

      uglify: {
         netskrafl_js: {
            src: 'static/netskrafl.js',
            dest: 'static/netskrafl.min.js'
         },
         main_js: {
            src: 'static/main.js',
            dest: 'static/main.min.js'
         },
         wait_js: {
            src: 'static/wait.js',
            dest: 'static/wait.min.js'
         }
      },

      less: {
         development: {
            files: {
                'static/skrafl-curry.css': ['static/skrafl-curry.less'],
                'static/skrafl-desat.css': ['static/skrafl-desat.less']
            },
            options: {
            }
         },
         production: {
            files: {
                'static/skrafl-curry.css': ['static/skrafl-curry.less'],
                'static/skrafl-desat.css': ['static/skrafl-desat.less']
            },
            options: {
                cleancss: true
            }
         }
      },

      watch: {
         concat: {
            files: ['static/js/*.js'],
            tasks: ['concat']
         },
         jshint: {
            files: ['static/js/*.js'],
            tasks: ['jshint'],
            options: { spawn: false }
         },
         uglify_netskrafl: {
            files: ['static/netskrafl.js'],
            tasks: ['uglify:netskrafl_js'],
            options: { spawn: false }
         },
         uglify_main: {
            files: ['static/main.js'],
            tasks: ['uglify:main_js'],
            options: { spawn: false }
         },
         uglify_wait: {
            files: ['static/wait.js'],
            tasks: ['uglify:wait_js'],
            options: { spawn: false }
         },
         less: {
            files: ['static/*.less', 'static\\*.less', 'static/main.less', 'static\\main.less'],
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
   grunt.registerTask('make', ['concat', 'uglify', 'less']);

   function startsWith(s, t) {
      return s.lastIndexOf(t, 0) === 0;
   }

   // On watch events configure jshint:all to only run on changed file
   grunt.event.on('watch', function(action, filepath) {
      console.log("watch: " + filepath);
      if (startsWith(filepath, "static/js/") || startsWith(filepath, "static\\js\\"))
         grunt.config('jshint.all.src', [ filepath ]);
   });

};
