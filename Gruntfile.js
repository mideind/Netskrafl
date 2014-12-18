
module.exports = function (grunt) {

   grunt.initConfig({

      // See: http://www.jshint.com/docs/
      jshint: {
         all: {
            src: 'static/netskrafl.js',
            options: {
               bitwise: true,
               camelcase: true,
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
               predef: ['$', 'document', 'prompt', 'alert', 'console', 'Mousetrap',
                  'localPlayer', 'placeTiles', 'initBag', 'initMoveList', 'gameId']
            }
         }
      },

      uglify: {
         all: {
            files: {
               'static/netskrafl.min.js': 'static/netskrafl.js'
            }
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
         jshint: {
            files: 'static/netskrafl.js',
            tasks: 'jshint'
         },
         uglify: {
            files: 'static/netskrafl.js',
            tasks: 'uglify'
         },
         less: {
            files: 'static/*.less',
            tasks: 'less:development'
         },
         configFiles: {
            files: 'Gruntfile.js',
         }
      }

   });

   // Load Grunt tasks declared in the package.json file
   require('matchdep').filterDev('grunt-*').forEach(grunt.loadNpmTasks);
   /*
   grunt.loadNpmTasks('grunt-contrib-jshint');
   grunt.loadNpmTasks('grunt-contrib-watch');
   grunt.loadNpmTasks('grunt-contrib-uglify');
   grunt.loadNpmTasks('grunt-contrib-less');
   */

   grunt.registerTask('default', ['watch']);

};